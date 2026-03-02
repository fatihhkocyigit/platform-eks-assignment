import sys
import os
import pytest
from unittest.mock import Mock
from botocore.exceptions import ClientError
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda_function"))
from lambda_function import generate_helm_values, get_environment_from_ssm


# ==============================================================================
# Tests for generate_helm_values() function
# ==============================================================================

class TestGenerateHelmValues:

    def test_development_replica_count(self):
        result = generate_helm_values("development")
        assert result == {"controller": {"replicaCount": 1}}

    def test_staging_replica_count(self):
        result = generate_helm_values("staging")
        assert result == {"controller": {"replicaCount": 2}}

    def test_production_replica_count(self):
        result = generate_helm_values("production")
        assert result == {"controller": {"replicaCount": 2}}


    # Case sensitivity cases
    def test_uppercase_environment_name(self):
        result = generate_helm_values("PRODUCTION")
        assert result == {"controller": {"replicaCount": 2}}


    # Whitespace cases
    def test_environment_with_leading_whitespace(self):
        result = generate_helm_values("  production")
        assert result == {"controller": {"replicaCount": 2}}

    def test_environment_with_trailing_whitespace(self):
        result = generate_helm_values("staging  ")
        assert result == {"controller": {"replicaCount": 2}}



    # Error cases
    def test_invalid_environment_error(self):
        with pytest.raises(ValueError, match="Unknown environment"):
            generate_helm_values("invalid")



class TestGetEnvironmentFromSSM:

    def test_successful_ssm_retrieval(self):
        mock_ssm = Mock()
        mock_ssm.get_parameter.return_value = {
            "Parameter": {
                "Value": "production"
            }
        }

        result = get_environment_from_ssm(mock_ssm, "/platform/account/env")
        assert result == "production"
        mock_ssm.get_parameter.assert_called_once_with(
            Name="/platform/account/env",
            WithDecryption=False
        )

    def test_parameter_not_found_error(self):
        mock_ssm = Mock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "Parameter not found"}},
            "GetParameter"
        )

        with pytest.raises(ValueError, match="does not exist"):
            get_environment_from_ssm(mock_ssm, "/nonexistent/param")

    def test_access_denied_permission_error(self):
        mock_ssm = Mock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
            "GetParameter"
        )

        with pytest.raises(PermissionError, match="Insufficient permissions"):
            get_environment_from_ssm(mock_ssm, "/platform/account/env")





if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=lambda_function", "--cov-report=term-missing"])
