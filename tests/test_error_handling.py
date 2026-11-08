"""
tests/test_error_handling.py
-----------------------------
QA tests for error handling and graceful degradation.

Tests cover:
  - PostgreSQL unavailable (mocked)
  - Missing environment variables
  - Invalid Groq API key
  - Groq API timeout
  - Malformed AI response
  - Sentence Transformer model unavailable
  - Empty database
  - Invalid user input
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from core.security import hash_password, validate_password_strength, sanitise_string


# ---------------------------------------------------------------------------
# Groq API error handling
# ---------------------------------------------------------------------------

class TestGroqAPIErrors:
    @patch("services.ai.classifier.settings")
    @patch("services.ai.classifier.chat_completion")
    def test_invalid_api_key_returns_fallback(self, mock_chat, mock_settings):
        mock_settings.ai_enabled = True
        mock_chat.side_effect = Exception("401 Unauthorized: Invalid API key")
        from services.ai.classifier import classify_request
        result = classify_request("Test title", "Test description")
        assert not result.succeeded
        assert result.category == "other"
        assert result.error is not None

    @patch("services.ai.classifier.settings")
    @patch("services.ai.classifier.chat_completion")
    def test_api_timeout_returns_fallback(self, mock_chat, mock_settings):
        mock_settings.ai_enabled = True
        mock_chat.side_effect = TimeoutError("Request timed out after 30s")
        from services.ai.classifier import classify_request
        result = classify_request("Test title", "Test description")
        assert not result.succeeded
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()

    @patch("services.ai.classifier.settings")
    @patch("services.ai.classifier.chat_completion")
    def test_rate_limit_returns_fallback(self, mock_chat, mock_settings):
        mock_settings.ai_enabled = True
        mock_chat.side_effect = Exception("429 Too Many Requests")
        from services.ai.classifier import classify_request
        result = classify_request("Test title", "Test description")
        assert not result.succeeded

    @patch("services.ai.classifier.settings")
    @patch("services.ai.classifier.chat_completion")
    def test_connection_refused_returns_fallback(self, mock_chat, mock_settings):
        mock_settings.ai_enabled = True
        mock_chat.side_effect = ConnectionError("Connection refused")
        from services.ai.classifier import classify_request
        result = classify_request("Test title", "Test description")
        assert not result.succeeded

    @patch("services.ai.priority_advisor.settings")
    @patch("services.ai.priority_advisor.chat_completion")
    def test_priority_api_failure_uses_safety_floor(self, mock_chat, mock_settings):
        mock_settings.ai_enabled = True
        mock_chat.side_effect = Exception("500 Internal Server Error")
        from services.ai.priority_advisor import recommend_priority
        result = recommend_priority("Power outage", "The power is out in the entire building")
        # Safety rules should still fire and set the floor
        assert result.priority == "high"


# ---------------------------------------------------------------------------
# Malformed AI response handling
# ---------------------------------------------------------------------------

class TestMalformedAIResponses:
    def test_classifier_handles_non_json(self):
        from services.ai.classifier import _parse_classification_response
        result = _parse_classification_response("This is definitely not JSON")
        assert not result.succeeded
        assert result.category == "other"

    def test_classifier_handles_empty_string(self):
        from services.ai.classifier import _parse_classification_response
        result = _parse_classification_response("")
        assert not result.succeeded

    def test_classifier_handles_partial_json(self):
        from services.ai.classifier import _parse_classification_response
        result = _parse_classification_response('{"category": "plumbing", "summary":')
        assert not result.succeeded

    def test_classifier_handles_json_with_extra_text(self):
        from services.ai.classifier import _parse_classification_response
        raw = 'Here is the result: {"category": "hvac", "summary": "AC broken.", "priority": "high", "confidence": 0.8} That is all.'
        result = _parse_classification_response(raw)
        assert result.succeeded
        assert result.category == "hvac"

    def test_priority_handles_malformed(self):
        from services.ai.priority_advisor import _parse_priority_response
        result = _parse_priority_response("not json")
        assert not result.succeeded
        assert result.priority == "medium"

    def test_priority_handles_empty(self):
        from services.ai.priority_advisor import _parse_priority_response
        result = _parse_priority_response("")
        assert not result.succeeded
        assert result.priority == "medium"


# ---------------------------------------------------------------------------
# Sentence Transformer unavailability
# ---------------------------------------------------------------------------

class TestSentenceTransformerUnavailable:
    @patch("services.ai.similarity.settings")
    def test_disabled_returns_empty_list(self, mock_settings):
        mock_settings.semantic_search_enabled = False
        from services.ai.similarity import find_similar_requests, encode_request
        assert find_similar_requests("Title", "Desc", []) == []
        assert encode_request("Title", "Desc") is None

    @patch("services.ai.similarity.settings")
    def test_model_import_failure_returns_none(self, mock_settings):
        mock_settings.semantic_search_enabled = True
        with patch("services.ai.similarity._get_model", side_effect=ImportError("No module")):
            from services.ai.similarity import encode_request
            result = encode_request("Title", "Desc")
            assert result is None

    @patch("services.ai.similarity.settings")
    def test_model_load_failure_returns_none(self, mock_settings):
        mock_settings.semantic_search_enabled = True
        with patch("services.ai.similarity._get_model", side_effect=RuntimeError("Model download failed")):
            from services.ai.similarity import encode_request
            result = encode_request("Title", "Desc")
            assert result is None


# ---------------------------------------------------------------------------
# Invalid user input
# ---------------------------------------------------------------------------

class TestInvalidUserInput:
    def test_empty_password_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            hash_password("")

    def test_whitespace_password_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            hash_password("   ")

    def test_too_long_password_rejected(self):
        with pytest.raises(ValueError, match="72 characters"):
            hash_password("A" * 73)

    def test_weak_password_rejected(self):
        errors = validate_password_strength("abc")
        assert len(errors) >= 3

    def test_empty_comment_rejected(self, db_session, make_user, make_request):
        from database.crud.comment_crud import add_comment
        user = make_user(username="comment_test")
        req = make_request(requester=user, reference_suffix="CMT1")
        db_session.flush()
        with pytest.raises(ValueError, match="must not be empty"):
            add_comment(db_session, req.id, user.id, "   ")

    def test_too_long_comment_rejected(self, db_session, make_user, make_request):
        from database.crud.comment_crud import add_comment, COMMENT_MAX_LEN
        user = make_user(username="long_comment_test")
        req = make_request(requester=user, reference_suffix="CMT2")
        db_session.flush()
        with pytest.raises(ValueError, match="maximum length"):
            add_comment(db_session, req.id, user.id, "x" * (COMMENT_MAX_LEN + 1))

    def test_create_user_with_duplicate_username_rejected(self, db_session, make_user):
        from database.crud.user_crud import create_user
        from database.models.user import UserRole
        make_user(username="duplicate")
        with pytest.raises(ValueError, match="already taken"):
            create_user(
                db_session, "duplicate", "other@test.local", "Other User", "Other@Pass1",
                role=UserRole.REQUESTER,
            )

    def test_create_location_with_empty_name_rejected(self, db_session):
        from database.crud.location_crud import create_location
        with pytest.raises(ValueError, match="must not be empty"):
            create_location(db_session, building_name="   ")

    def test_sanitise_string_truncates(self):
        assert sanitise_string("a" * 300, max_length=100) == "a" * 100

    def test_sanitise_string_strips_whitespace(self):
        assert sanitise_string("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# Missing environment variables
# ---------------------------------------------------------------------------

class TestMissingEnvVars:
    def test_settings_validate_reports_missing_groq_key(self):
        from core.config import _Settings
        s = _Settings()
        s.GROQ_API_KEY = ""
        issues = s.validate()
        has_groq_issue = any("GROQ_API_KEY" in i for i in issues)
        assert has_groq_issue, "Should report missing GROQ_API_KEY"

    def test_ai_disabled_when_no_key(self):
        from core.config import _Settings
        s = _Settings()
        s.GROQ_API_KEY = ""
        assert s.ai_enabled is False

    def test_semantic_search_disabled_when_ai_disabled(self):
        from core.config import _Settings
        s = _Settings()
        s.ENABLE_AI_FEATURES = False
        assert s.semantic_search_enabled is False


# ---------------------------------------------------------------------------
# PostgreSQL unavailable (simulated via mock)
# ---------------------------------------------------------------------------

class TestDatabaseUnavailable:
    def test_check_db_connection_failure(self):
        """check_db_connection should return (False, msg) when PG is unavailable."""
        from database.connection import check_db_connection
        from sqlalchemy.exc import OperationalError

        with patch("database.connection.engine") as mock_engine:
            mock_engine.connect.side_effect = OperationalError(
                "statement", {}, Exception("connection refused")
            )
            ok, msg = check_db_connection()
            assert ok is False
            assert "Cannot reach PostgreSQL" in msg or "connection refused" in msg.lower()

    def test_classifier_works_without_db(self):
        """Classifier should work (or fail gracefully) even without a DB connection,
        since it only needs the Groq API."""
        from services.ai.classifier import _parse_classification_response
        # This function is pure — no DB needed
        raw = json.dumps({
            "category": "plumbing", "summary": "Test.", "priority": "low", "confidence": 0.5,
        })
        result = _parse_classification_response(raw)
        assert result.succeeded
