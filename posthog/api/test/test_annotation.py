from datetime import datetime
from unittest.mock import patch

from zoneinfo import ZoneInfo
from django.utils.timezone import now
from rest_framework import status
from parameterized import parameterized

from posthog.models import Annotation, Organization, Team, User
from posthog.test.base import (
    APIBaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries_context,
    FuzzyInt,
)


class TestAnnotation(APIBaseTest, QueryMatchingTest):
    @patch("posthog.api.annotation.report_user_action")
    def test_retrieving_annotation(self, mock_capture):
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            content="hello world!",
        )

        # Annotation creation is not reported to PostHog because it has no created_by
        mock_capture.assert_not_called()

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
        assert len(response["results"]) == 1
        assert response["results"][0]["content"] == "hello world!"

    @patch("posthog.api.annotation.report_user_action")
    def test_retrieving_annotation_is_not_n_plus_1(self, _mock_capture) -> None:
        """
        see https://sentry.io/organizations/posthog/issues/3706110236/events/db0167ece56649f59b013cbe9de7ba7a/?project=1899813
        """
        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            assert len(response["results"]) == 0

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            created_by=User.objects.create_and_join(self.organization, "one", ""),
            content=now().isoformat(),
        )

        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            assert len(response["results"]) == 1

        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_at="2020-01-04T12:00:00Z",
            created_by=User.objects.create_and_join(self.organization, "two", ""),
            content=now().isoformat(),
        )

        with self.assertNumQueries(FuzzyInt(8, 9)), snapshot_postgres_queries_context(self):
            response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()
            assert len(response["results"]) == 2

    def test_org_scoped_annotations_are_returned_between_projects(self):
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        Annotation.objects.create(
            organization=self.organization,
            team=second_team,
            created_by=self.user,
            content="Cross-project annotation!",
            scope=Annotation.Scope.ORGANIZATION,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/annotations/").json()

        assert len(response["results"]) == 1
        assert response["results"][0]["content"] == "Cross-project annotation!"

    def test_cannot_fetch_annotations_of_org_user_does_not_belong_to(self):
        separate_org, _, separate_team = Organization.objects.bootstrap(None, name="Second team")
        Annotation.objects.create(
            organization=separate_org,
            team=separate_team,
            content="Intra-project annotation!",
            scope=Annotation.Scope.PROJECT,
        )
        Annotation.objects.create(
            organization=separate_org,
            team=separate_team,
            content="Cross-project annotation!",
            scope=Annotation.Scope.ORGANIZATION,
        )

        response_1 = self.client.get(f"/api/projects/{separate_team.id}/annotations/")

        assert response_1.status_code == 403
        assert response_1.json() == self.permission_denied_response("You don't have access to the project.")

        response_2 = self.client.get(f"/api/projects/{self.team.id}/annotations/")

        assert response_2.status_code == 200
        assert response_2.json()["results"] == []

    @patch("posthog.api.annotation.report_user_action")
    def test_creating_annotation(self, mock_capture):
        team2 = Organization.objects.bootstrap(None)[2]

        self.client.force_login(self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": "Marketing campaign",
                "scope": "organization",
                "date_marker": "2020-01-01T00:00:00.000000Z",
                "team": team2.pk,  # make sure this is set automatically
            },
        )
        date_marker: datetime = datetime(2020, 1, 1, 0, 0, 0).replace(tzinfo=ZoneInfo("UTC"))
        assert response.status_code == status.HTTP_201_CREATED
        instance = Annotation.objects.get(pk=response.json()["id"])
        assert instance.content == "Marketing campaign"
        assert instance.scope == "organization"
        assert instance.date_marker == date_marker
        assert instance.team == self.team
        assert instance.creation_type == "USR"

        # Assert analytics are sent
        mock_capture.assert_called_once_with(
            self.user,
            "annotation created",
            {"scope": "organization", "date_marker": date_marker},
        )

    @patch("posthog.api.annotation.report_user_action")
    def test_can_create_annotations_as_a_bot(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {
                "content": "Marketing campaign",
                "scope": "organization",
                "date_marker": "2020-01-01T00:00:00.000000Z",
                "team": self.team.pk,
                "creation_type": "GIT",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        instance = Annotation.objects.get(pk=response.json()["id"])
        assert instance.creation_type == "GIT"

        get_created_response = self.client.get(f"/api/projects/{self.team.id}/annotations/{instance.id}/")
        assert get_created_response.json()["creation_type"] == "GIT"

    @patch("posthog.api.annotation.report_user_action")
    def test_downgrading_scope_from_org_to_project_uses_team_id_from_api(self, mock_capture):
        second_team = Team.objects.create(organization=self.organization, name="Second team")
        test_annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="hello world!",
            scope=Annotation.Scope.ORGANIZATION,
        )
        mock_capture.reset_mock()  # Disregard the "annotation created" call
        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/projects/{second_team.id}/annotations/{test_annotation.pk}/",
            {"scope": Annotation.Scope.PROJECT},
        )
        test_annotation.refresh_from_db()

        assert response.status_code == status.HTTP_200_OK
        assert test_annotation.scope == Annotation.Scope.PROJECT
        # Previously the project was `self.team``, but after downgrading scope from "Organization" to "Project", we want
        # the current project (i.e. `second_team`, whose ID was used in the API request) to own the annotation.
        # This is so that an annotation doesn't disappear when its downgraded and it actually belonged to a different
        # project than the one the user is viewing.
        assert test_annotation.team == second_team

    def test_updating_annotation(self):
        test_annotation = Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            created_by=self.user,
            created_at="2020-01-04T12:00:00Z",
            content="hello world!",
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/annotations/{test_annotation.pk}/",
            {"content": "Updated text", "scope": "organization"},
        )
        test_annotation.refresh_from_db()

        assert response.status_code == status.HTTP_200_OK
        assert test_annotation.content == "Updated text"
        assert test_annotation.scope == "organization"
        assert test_annotation.date_marker is None

    def test_deleting_annotation(self):
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = Annotation.objects.create(organization=self.organization, team=self.team, created_by=self.user)
        self.client.force_login(new_user)

        with patch("posthog.api.team.report_user_action"):
            response = self.client.delete(f"/api/projects/{self.team.id}/annotations/{instance.pk}/")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert Annotation.objects.filter(pk=instance.pk).exists()

    @parameterized.expand(
        [
            ("organization", "organization scoped", 1),
            ("project", "project scoped", 1),
            ("insight", "insight scoped", 1),
            ("dashboard_item", "insight scoped", 1),
            ("dashboard", "dashboard scoped", 1),
            (None, None, 4),
        ]
    )
    def test_annotation_can_be_filtered_by_scope(self, scope: str, expected_content: str, expected_result_count: int):
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="organization scoped",
            scope=Annotation.Scope.ORGANIZATION,
        )
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="project scoped",
            scope=Annotation.Scope.PROJECT,
        )
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="insight scoped",
            scope=Annotation.Scope.INSIGHT,
        )
        Annotation.objects.create(
            organization=self.organization,
            team=self.team,
            content="dashboard scoped",
            scope=Annotation.Scope.DASHBOARD,
        )

        scope_query_param = f"?scope={scope}" if scope else ""
        response = self.client.get(f"/api/projects/{self.team.id}/annotations/{scope_query_param}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) == expected_result_count
        if expected_result_count == 1:
            assert response.json()["results"][0]["content"] == expected_content
