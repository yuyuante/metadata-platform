import pytest

from emip.identity import normalize_identifier, suffix_identity_keys


def test_normalize_identifier_supports_sql_quoting_and_case() -> None:
    assert normalize_identifier("[dbo].[STKOUT]") == ("dbo", "stkout")
    assert normalize_identifier('"dbo"."STKOUT"') == ("dbo", "stkout")


def test_suffix_identity_keys_supports_informatica_prefixes() -> None:
    keys = suffix_identity_keys(
        "SVELAH::wf_MBAH_SYNC::s_m_MBAHSYNC_STKOUT::sc_svel_STKOUT",
        ("sc_svel_", "sc_"),
    )
    assert ("stkout",) in keys


@pytest.mark.parametrize(
    "suffix",
    ("_INSERT", "_DELETE", "_UPDATE", "_UPSERT", "_INS", "_DEL", "_UPD"),
)
def test_suffix_identity_keys_supports_informatica_operation_suffixes(
    suffix: str,
) -> None:
    keys = suffix_identity_keys(
        f"SVEL_MS::wf_MB_AI7100B::s_m_AI7100B::sc_svel_STKOUT{suffix}",
        ("sc_svel_", "sc_"),
        ("_insert", "_delete", "_update", "_upsert", "_ins", "_del", "_upd"),
    )
    assert ("stkout",) in keys


def test_suffix_identity_keys_does_not_strip_unknown_suffixes() -> None:
    keys = suffix_identity_keys(
        "sc_svel_STKOUT_archive",
        ("sc_svel_", "sc_"),
        ("_insert", "_delete", "_update", "_upsert", "_ins", "_del", "_upd"),
    )
    assert ("stkout",) not in keys
