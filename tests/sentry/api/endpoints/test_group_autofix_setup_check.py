from unittest.mock import patch

from sentry.api.helpers.autofix import AutofixCodebaseIndexingStatus
from sentry.models.integrations.repository_project_path_config import RepositoryProjectPathConfig
from sentry.models.repository import Repository
from sentry.silo.base import SiloMode
from sentry.testutils.cases import APITestCase, SnubaTestCase
from sentry.testutils.helpers.features import apply_feature_flag_on_cls, with_feature
from sentry.testutils.silo import assume_test_silo_mode


@apply_feature_flag_on_cls("projects:ai-autofix")
class GroupAIAutofixEndpointSuccessTest(APITestCase, SnubaTestCase):
    def setUp(self):
        super().setUp()

        integration = self.create_integration(organization=self.organization, external_id="1")

        with assume_test_silo_mode(SiloMode.CONTROL):
            self.org_integration = integration.add_organization(self.organization, self.user)

        self.repo = Repository.objects.create(
            organization_id=self.organization.id,
            name="example",
            integration_id=integration.id,
        )
        self.code_mapping = self.create_code_mapping(
            repo=self.repo,
            project=self.project,
            stack_root="sentry/",
            source_root="sentry/",
        )
        self.organization.update_option("sentry:gen_ai_consent", True)

    @patch(
        "sentry.api.endpoints.group_autofix_setup_check.get_repos_and_access",
        return_value=[
            {
                "provider": "github",
                "owner": "getsentry",
                "name": "seer",
                "external_id": "123",
                "ok": True,
            }
        ],
    )
    @patch(
        "sentry.api.endpoints.group_autofix_setup_check.get_project_codebase_indexing_status",
        return_value=AutofixCodebaseIndexingStatus.UP_TO_DATE,
    )
    def test_successful_setup(self, mock_update_codebase_index, mock_get_repos_and_access):
        """
        Everything is set up correctly, should respond with OKs.
        """
        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data == {
            "genAIConsent": {
                "ok": True,
                "reason": None,
            },
            "integration": {
                "ok": True,
                "reason": None,
            },
            "githubWriteIntegration": {
                "ok": True,
                "repos": [
                    {
                        "provider": "github",
                        "owner": "getsentry",
                        "name": "seer",
                        "external_id": "123",
                        "ok": True,
                    }
                ],
            },
            "codebaseIndexing": {
                "ok": True,
            },
        }

    @with_feature("organizations:autofix-disable-codebase-indexing")
    @patch(
        "sentry.api.endpoints.group_autofix_setup_check.get_repos_and_access",
        return_value=[
            {
                "provider": "github",
                "owner": "getsentry",
                "name": "seer",
                "external_id": "123",
                "ok": True,
            }
        ],
    )
    @patch(
        "sentry.api.endpoints.group_autofix_setup_check.get_project_codebase_indexing_status",
        return_value=AutofixCodebaseIndexingStatus.NOT_INDEXED,
    )
    def test_successful_with_codebase_indexing_disabled_flag(
        self, mock_update_codebase_index, mock_get_repos_and_access
    ):
        """
        Everything is set up correctly, should respond with OKs.
        """
        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data == {
            "genAIConsent": {
                "ok": True,
                "reason": None,
            },
            "integration": {
                "ok": True,
                "reason": None,
            },
            "githubWriteIntegration": {
                "ok": True,
                "repos": [
                    {
                        "provider": "github",
                        "owner": "getsentry",
                        "name": "seer",
                        "external_id": "123",
                        "ok": True,
                    }
                ],
            },
            "codebaseIndexing": {
                "ok": True,
            },
        }


@apply_feature_flag_on_cls("projects:ai-autofix")
class GroupAIAutofixEndpointFailureTest(APITestCase, SnubaTestCase):
    def test_no_gen_ai_consent(self):
        self.organization.update_option("sentry:gen_ai_consent", False)

        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data["genAIConsent"] == {
            "ok": False,
            "reason": None,
        }

    def test_no_code_mappings(self):
        RepositoryProjectPathConfig.objects.filter(
            organization_integration_id=self.organization_integration.id
        ).delete()

        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data["integration"] == {
            "ok": False,
            "reason": "integration_no_code_mappings",
        }

    def test_missing_integration(self):
        with assume_test_silo_mode(SiloMode.CONTROL):
            self.organization_integration.delete()

        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data["integration"] == {
            "ok": False,
            "reason": "integration_missing",
        }

    @patch(
        "sentry.api.endpoints.group_autofix_setup_check.get_repos_and_access",
        return_value=[
            {
                "provider": "github",
                "owner": "getsentry",
                "name": "seer",
                "external_id": "123",
                "ok": False,
            },
            {
                "provider": "github",
                "owner": "getsentry",
                "name": "sentry",
                "external_id": "234",
                "ok": True,
            },
        ],
    )
    def test_repo_write_access_not_ready(self, mock_get_repos_and_access):
        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data["githubWriteIntegration"] == {
            "ok": False,
            "repos": [
                {
                    "provider": "github",
                    "owner": "getsentry",
                    "name": "seer",
                    "external_id": "123",
                    "ok": False,
                },
                {
                    "provider": "github",
                    "owner": "getsentry",
                    "name": "sentry",
                    "external_id": "234",
                    "ok": True,
                },
            ],
        }

    @patch(
        "sentry.api.endpoints.group_autofix_setup_check.get_repos_and_access",
        return_value=[],
    )
    def test_repo_write_access_no_repos(self, mock_get_repos_and_access):
        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data["githubWriteIntegration"] == {
            "ok": False,
            "repos": [],
        }

    @patch(
        "sentry.api.endpoints.group_autofix_setup_check.get_project_codebase_indexing_status",
        return_value=AutofixCodebaseIndexingStatus.NOT_INDEXED,
    )
    def test_codebase_indexing_not_done(self, mock_get_project_codebase_indexing_status):
        group = self.create_group()
        self.login_as(user=self.user)
        url = f"/api/0/issues/{group.id}/autofix/setup/"
        response = self.client.get(url, format="json")

        assert response.status_code == 200
        assert response.data["codebaseIndexing"] == {
            "ok": False,
        }
