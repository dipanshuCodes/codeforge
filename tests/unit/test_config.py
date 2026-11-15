import pytest

from codeforge.config import ConfigError, load_settings


def test_loads_identity_from_env():
    s = load_settings({"CODEFORGE_USER_ID": "u-alice", "CODEFORGE_ROLE": "student"})
    assert s.user_id == "u-alice"
    assert s.role == "student"
    assert s.large_model == "openai/gpt-oss-120b"
    assert s.small_model == "openai/gpt-oss-20b"
    assert s.sandbox_timeout_s == 10.0
    assert s.max_output_bytes == 10_240
    assert s.max_repair_attempts == 0


def test_missing_user_id_raises():
    with pytest.raises(ConfigError):
        load_settings({})


def test_blank_user_id_raises():
    with pytest.raises(ConfigError):
        load_settings({"CODEFORGE_USER_ID": "  ", "CODEFORGE_ROLE": "student"})


def test_invalid_role_raises():
    with pytest.raises(ConfigError):
        load_settings({"CODEFORGE_USER_ID": "u-alice", "CODEFORGE_ROLE": "admin"})


def test_missing_role_raises():
    with pytest.raises(ConfigError):
        load_settings({"CODEFORGE_USER_ID": "u-alice"})


def test_db_path_override():
    s = load_settings(
        {"CODEFORGE_USER_ID": "u-alice", "CODEFORGE_ROLE": "instructor", "CODEFORGE_DB_PATH": "/tmp/x.db"}
    )
    assert s.db_path == "/tmp/x.db"
    assert s.role == "instructor"


# --- .env files ---------------------------------------------------------------------

from pathlib import Path

from codeforge.config import ENV_KEYS, load_env_files, parse_env_file

REPO_ROOT = Path(__file__).parents[2]


def test_parse_env_file():
    text = (
        "# comment\n\n"
        "CODEFORGE_USER_ID=u-alice\n"
        "export CODEFORGE_ROLE=student\n"
        'CODEFORGE_DB_PATH="/tmp/a b.db"\n'
        "GROQ_API_KEY='gsk_FAKEFAKEFAKEFAKE'\n"
        "not a pair\n"
        "EMPTY=\n"
    )
    assert parse_env_file(text) == {
        "CODEFORGE_USER_ID": "u-alice",
        "CODEFORGE_ROLE": "student",
        "CODEFORGE_DB_PATH": "/tmp/a b.db",
        "GROQ_API_KEY": "gsk_FAKEFAKEFAKEFAKE",
        "EMPTY": "",
    }


def test_load_env_files_precedence(tmp_path):
    (tmp_path / ".env").write_text("CODEFORGE_USER_ID=from-env\nCODEFORGE_ROLE=instructor\nCODEFORGE_DB_PATH=deployed.db\n")
    (tmp_path / ".env.local").write_text("CODEFORGE_USER_ID=from-local\nCODEFORGE_ROLE=\n")
    environ = {"CODEFORGE_DB_PATH": "from-shell.db"}
    load_env_files(tmp_path, environ)
    assert environ["CODEFORGE_DB_PATH"] == "from-shell.db"   # the shell wins
    assert environ["CODEFORGE_USER_ID"] == "from-local"      # .env.local beats .env
    assert environ["CODEFORGE_ROLE"] == "instructor"         # a blank value doesn't shadow


def test_load_env_files_without_files_is_a_no_op(tmp_path):
    environ: dict[str, str] = {}
    load_env_files(tmp_path, environ)
    assert environ == {}


def test_env_example_lists_every_config_key():
    # Rule: every config key read by CodeForge must appear in .env.example.
    example = parse_env_file((REPO_ROOT / ".env.example").read_text())
    assert set(ENV_KEYS) == set(example)


def test_env_example_holds_no_secret_values():
    example = parse_env_file((REPO_ROOT / ".env.example").read_text())
    assert example["GROQ_API_KEY"] == ""


def test_env_files_are_gitignored():
    ignored = (REPO_ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in ignored and ".env.local" in ignored
