"""CSV contract and row validation for the Week 3 sync worker."""

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional


CSV_HEADER = ["external_id", "name", "amount", "record_date"]
EXTERNAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
AMOUNT_PATTERN = re.compile(r"^(?:0|[0-9]+)(?:\.[0-9]{1,2})?$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ParsedCsv:
    total_records: int
    records: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    file_error: Optional[Dict[str, str]] = None


def _error(
    row_number: Optional[int],
    field_name: Optional[str],
    error_code: str,
    error_message: str,
    raw_row: Any = None,
) -> Dict[str, Any]:
    return {
        "row_number": row_number,
        "field_name": field_name,
        "error_code": error_code,
        "error_message": error_message,
        "raw_row": raw_row,
    }


def _file_error(code: str, message: str) -> ParsedCsv:
    return ParsedCsv(total_records=0, records=[], errors=[], file_error={"error_code": code, "error_message": message})


def _validate_row(
    row_number: int,
    row: List[str],
    seen_external_ids: set[str],
) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    raw_row = {CSV_HEADER[index]: row[index] for index in range(min(len(row), len(CSV_HEADER)))}
    errors: List[Dict[str, Any]] = []

    if len(row) != len(CSV_HEADER):
        errors.append(
            _error(
                row_number,
                None,
                "ROW_COLUMN_COUNT_MISMATCH",
                f"列数不正确，应为 {len(CSV_HEADER)} 列",
                {"values": row},
            )
        )
        return None, errors

    values = [value.strip() for value in row]
    data = dict(zip(CSV_HEADER, values))

    for field_name in CSV_HEADER:
        if not data[field_name]:
            errors.append(_error(row_number, field_name, "FIELD_REQUIRED", f"{field_name} 不能为空", raw_row))

    external_id = data["external_id"]
    normalized_external_id = external_id.upper()
    if external_id and not EXTERNAL_ID_PATTERN.fullmatch(external_id):
        errors.append(
            _error(
                row_number,
                "external_id",
                "EXTERNAL_ID_INVALID",
                "external_id 只能包含字母、数字、下划线和短横线",
                raw_row,
            )
        )
    elif external_id and normalized_external_id in seen_external_ids:
        errors.append(
            _error(
                row_number,
                "external_id",
                "EXTERNAL_ID_DUPLICATE",
                "external_id 在同一任务内重复",
                raw_row,
            )
        )

    name = data["name"]
    if name and len(name) > 128:
        errors.append(_error(row_number, "name", "NAME_TOO_LONG", "name 不能超过 128 个字符", raw_row))

    amount: Optional[Decimal] = None
    amount_text = data["amount"]
    if amount_text:
        if not AMOUNT_PATTERN.fullmatch(amount_text):
            errors.append(_error(row_number, "amount", "AMOUNT_INVALID", "amount 必须是非负数字且最多两位小数", raw_row))
        else:
            try:
                amount = Decimal(amount_text).quantize(Decimal("0.01"))
            except InvalidOperation:
                errors.append(_error(row_number, "amount", "AMOUNT_INVALID", "amount 不是有效金额", raw_row))
            else:
                if amount >= Decimal("10000000000"):
                    errors.append(_error(row_number, "amount", "AMOUNT_INVALID", "amount 超出 DECIMAL(12,2) 范围", raw_row))

    record_date: Optional[date] = None
    date_text = data["record_date"]
    if date_text:
        if not DATE_PATTERN.fullmatch(date_text):
            errors.append(_error(row_number, "record_date", "DATE_INVALID", "record_date 必须是 YYYY-MM-DD 格式", raw_row))
        else:
            try:
                record_date = datetime.strptime(date_text, "%Y-%m-%d").date()
            except ValueError:
                errors.append(_error(row_number, "record_date", "DATE_INVALID", "record_date 不是有效日期", raw_row))

    if external_id and EXTERNAL_ID_PATTERN.fullmatch(external_id):
        seen_external_ids.add(normalized_external_id)

    if errors:
        return None, errors

    return {
        "row_number": row_number,
        "raw_row": raw_row,
        "external_id": normalized_external_id,
        "name": name,
        "amount": amount,
        "record_date": record_date,
    }, []


def parse_csv_file(path: str, max_records: int = 10000) -> ParsedCsv:
    """Parse a UTF-8 CSV file and return normalized valid rows plus errors."""

    try:
        handle = Path(path).open("r", encoding="utf-8-sig", newline="")
    except UnicodeDecodeError:
        return _file_error("FILE_ENCODING_INVALID", "文件不是可识别的 UTF-8 编码")
    except OSError:
        return _file_error("FILE_UNREADABLE", "文件无法读取")

    try:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return _file_error("FILE_EMPTY", "文件为空或只有表头")
        except UnicodeDecodeError:
            return _file_error("FILE_ENCODING_INVALID", "文件不是可识别的 UTF-8 编码")
        except csv.Error:
            return _file_error("FILE_UNREADABLE", "CSV 文件无法解析")

        header = [value.strip() for value in header]
        if header != CSV_HEADER:
            return _file_error(
                "CSV_HEADER_INVALID",
                "CSV 表头必须按顺序包含 external_id、name、amount、record_date，且不能包含额外字段",
            )

        records: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        seen_external_ids: set[str] = set()
        total_records = 0

        try:
            for row in reader:
                if not row or all(not value.strip() for value in row):
                    continue
                total_records += 1
                if total_records > max_records:
                    return _file_error("FILE_TOO_MANY_ROWS", f"有效数据行不能超过 {max_records} 行")
                parsed, row_errors = _validate_row(reader.line_num, row, seen_external_ids)
                if parsed is not None:
                    records.append(parsed)
                errors.extend(row_errors)
        except UnicodeDecodeError:
            return _file_error("FILE_ENCODING_INVALID", "文件不是可识别的 UTF-8 编码")
        except csv.Error:
            return _file_error("FILE_UNREADABLE", "CSV 文件无法解析")

        if total_records == 0:
            return _file_error("FILE_EMPTY", "文件为空或只有表头")

        return ParsedCsv(total_records=total_records, records=records, errors=errors)
    finally:
        handle.close()
