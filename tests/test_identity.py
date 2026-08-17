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
