"""Tests for spec detection."""

from unittest.mock import patch

from agent_arborist.spec import (
    parse_spec_from_string,
    detect_spec_from_git,
    SpecInfo,
)


class TestParseSpecFromString:
    def test_simple_spec(self):
        result = parse_spec_from_string("001-my-feature")
        assert result == ("001", "my-feature")

    def test_complex_spec(self):
        result = parse_spec_from_string("002-bl-17-rabbitmq-event-bus")
        assert result == ("002", "bl-17-rabbitmq-event-bus")

    def test_three_digit_required(self):
        assert parse_spec_from_string("01-feature") is None
        assert parse_spec_from_string("1-feature") is None
        assert parse_spec_from_string("1234-feature") is None

    def test_dash_required(self):
        assert parse_spec_from_string("001feature") is None
        assert parse_spec_from_string("001_feature") is None

    def test_no_match_returns_none(self):
        assert parse_spec_from_string("main") is None
        assert parse_spec_from_string("feature/something") is None
        assert parse_spec_from_string("") is None


class TestDetectSpecFromGit:
    @patch("agent_arborist.spec.get_git_branch")
    def test_spec_in_branch_root(self, mock_branch):
        mock_branch.return_value = "002-my-feature"
        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "002"
        assert result.name == "my-feature"
        assert result.source == "git"
        assert result.branch == "002-my-feature"

    @patch("agent_arborist.spec.get_git_branch")
    def test_spec_in_branch_with_phase(self, mock_branch):
        mock_branch.return_value = "002-my-feature/phase-1"
        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "002"
        assert result.name == "my-feature"

    @patch("agent_arborist.spec.get_git_branch")
    def test_spec_in_branch_with_task(self, mock_branch):
        mock_branch.return_value = "002-my-feature/phase-1/T001"
        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "002"
        assert result.name == "my-feature"

    @patch("agent_arborist.spec.get_git_branch")
    def test_spec_in_feature_prefix(self, mock_branch):
        mock_branch.return_value = "feature/001-new-thing"
        result = detect_spec_from_git()
        assert result.found
        assert result.spec_id == "001"
        assert result.name == "new-thing"

    @patch("agent_arborist.spec.get_git_branch")
    def test_no_spec_in_main(self, mock_branch):
        mock_branch.return_value = "main"
        result = detect_spec_from_git()
        assert not result.found
        assert result.error is not None
        assert "main" in result.error
        assert result.branch == "main"

    @patch("agent_arborist.spec.get_git_branch")
    def test_no_spec_in_feature_branch(self, mock_branch):
        mock_branch.return_value = "feature/add-login"
        result = detect_spec_from_git()
        assert not result.found
        assert result.error is not None

    @patch("agent_arborist.spec.get_git_branch")
    def test_not_in_git_repo(self, mock_branch):
        mock_branch.return_value = None
        result = detect_spec_from_git()
        assert not result.found
        assert "git" in result.error.lower()
