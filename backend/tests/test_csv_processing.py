from pathlib import Path

from app.csv_processing import parse_csv_file


def write_csv(tmp_path: Path, content: str) -> str:
    path = tmp_path / "input.csv"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_parse_csv_normalizes_valid_rows_and_collects_row_errors(tmp_path):
    path = write_csv(
        tmp_path,
        "external_id,name,amount,record_date\n"
        " s001 , 商品 A ,19.9,2026-01-01\n"
        "S001,商品 B,10,2026-01-02\n"
        "S003,,1.234,2026-02-30\n"
        "\n",
    )

    result = parse_csv_file(path)

    assert result.file_error is None
    assert result.total_records == 3
    assert len(result.records) == 1
    assert result.records[0]["external_id"] == "S001"
    assert str(result.records[0]["amount"]) == "19.90"
    assert {error["error_code"] for error in result.errors} == {
        "EXTERNAL_ID_DUPLICATE",
        "FIELD_REQUIRED",
        "AMOUNT_INVALID",
        "DATE_INVALID",
    }


def test_parse_csv_rejects_invalid_header(tmp_path):
    path = write_csv(tmp_path, "name,external_id,amount,record_date\n商品,ID,1,2026-01-01\n")

    result = parse_csv_file(path)

    assert result.file_error == {
        "error_code": "CSV_HEADER_INVALID",
        "error_message": "CSV 表头必须按顺序包含 external_id、name、amount、record_date，且不能包含额外字段",
    }


def test_parse_csv_reserves_valid_external_id_even_when_other_fields_are_invalid(tmp_path):
    path = write_csv(
        tmp_path,
        "external_id,name,amount,record_date\n"
        "A,first,not-a-number,2026-01-01\n"
        "a,second,1,2026-01-01\n",
    )

    result = parse_csv_file(path)

    assert result.records == []
    assert [error["error_code"] for error in result.errors] == [
        "AMOUNT_INVALID",
        "EXTERNAL_ID_DUPLICATE",
    ]


def test_parse_csv_rejects_empty_file_and_row_limit(tmp_path):
    empty_result = parse_csv_file(write_csv(tmp_path, "external_id,name,amount,record_date\n"))
    too_many_result = parse_csv_file(
        write_csv(tmp_path, "external_id,name,amount,record_date\nA,a,1,2026-01-01\nB,b,2,2026-01-01\n"),
        max_records=1,
    )

    assert empty_result.file_error["error_code"] == "FILE_EMPTY"
    assert too_many_result.file_error["error_code"] == "FILE_TOO_MANY_ROWS"


def test_parse_csv_reports_invalid_encoding(tmp_path):
    path = tmp_path / "invalid-encoding.csv"
    path.write_bytes(b"external_id,name,amount,record_date\n\xff\n")

    result = parse_csv_file(str(path))

    assert result.file_error["error_code"] == "FILE_ENCODING_INVALID"
