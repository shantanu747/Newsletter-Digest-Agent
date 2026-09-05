"""Unit tests for theme synthesis (P3)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import anthropic

from agent.trends.synthesis import cluster_ideas, synthesize_themes
from agent.utils.models import DigestEntry, EntityMention, Idea, Summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_idea(
    title: str,
    summary_text: str,
    entities: list[EntityMention] | None = None,
) -> Idea:
    return Idea(
        title=title,
        summary_text=summary_text,
        entities=tuple(entities) if entities else (),
    )


def _make_summary(
    email_id: str,
    sender: str,
    subject: str,
    ideas: list[Idea] | None = None,
    is_pass_through: bool = False,
) -> Summary:
    return Summary(
        email_id=email_id,
        sender=sender,
        subject=subject,
        summary_text="",
        word_count=0,
        generated_at=datetime(2026, 3, 9, 7, 1, 0, tzinfo=timezone.utc),
        ideas=tuple(ideas) if ideas else None,
    )


def _make_entry(
    email_id: str,
    sender: str,
    subject: str,
    ideas: list[Idea] | None = None,
    is_pass_through: bool = False,
    display_name: str = "",
) -> DigestEntry:
    summary = _make_summary(email_id, sender, subject, ideas, is_pass_through)
    return DigestEntry(
        summary=summary,
        is_pass_through=is_pass_through,
        display_name=display_name or sender,
    )


# ---------------------------------------------------------------------------
# TestClusterIdeas
# ---------------------------------------------------------------------------

class TestClusterIdeas:
    """Tests for cluster_ideas function."""

    def test_four_senders_sharing_two_entities_form_one_cluster(self):
        """Four newsletters covering same story with >=2 shared entities form one cluster."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        e3 = EntityMention(name="China", entity_type="country", sentiment="neutral")

        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Nvidia hit", "Nvidia faces new curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Chip curbs", "Export controls tighten on Nvidia", [e1, e2]),
            ], display_name="The AI Journal"),
            _make_entry("msg-3", "c@x.com", "Unusual Whales", [
                _make_idea("Nvidia drop", "Nvidia shares fall on China rules", [e1, e2, e3]),
            ], display_name="Unusual Whales"),
            _make_entry("msg-4", "d@x.com", "Kilo", [
                _make_idea("Semiconductor ban", "New export controls hit Nvidia hard", [e1, e2]),
            ], display_name="Kilo"),
        ]

        clusters = cluster_ideas(entries)
        assert len(clusters) == 1
        assert len(clusters[0]) == 4

    def test_three_ideas_from_one_sender_do_not_cluster(self):
        """FR-049: Ideas from single sender never form a cluster regardless of shared entities."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")

        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
                _make_idea("Idea 3", "Nvidia hit again", [e1, e2]),
            ], display_name="Bloomberg"),
        ]

        clusters = cluster_ideas(entries)
        assert len(clusters) == 0

    def test_single_shared_entity_does_not_link(self):
        """Only one shared entity should not create a link (need >= 2)."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        e3 = EntityMention(name="AI chips", entity_type="technology", sentiment="neutral")

        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "AI chips advance", [e1, e3]),
            ], display_name="The AI Journal"),
        ]

        clusters = cluster_ideas(entries)
        assert len(clusters) == 0

    def test_entity_matching_is_case_and_punctuation_insensitive(self):
        """normalize_key should make 'NVIDIA Corp.' match 'nvidia corp'."""
        e1a = EntityMention(name="NVIDIA Corp.", entity_type="company", sentiment="negative")
        e2a = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        e1b = EntityMention(name="nvidia corp", entity_type="company", sentiment="negative")
        e2b = EntityMention(name="export controls", entity_type="policy", sentiment="negative")

        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1a, e2a]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1b, e2b]),
            ], display_name="The AI Journal"),
        ]

        clusters = cluster_ideas(entries)
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_transitive_links_merge_into_one_cluster(self):
        """A-B share 2, B-C share 2, A-C share 0 -> all three in one cluster."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        e3 = EntityMention(name="China", entity_type="country", sentiment="neutral")
        e4 = EntityMention(name="semiconductors", entity_type="technology", sentiment="neutral")
        e5 = EntityMention(name="chips", entity_type="technology", sentiment="neutral")

        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("A", "Nvidia export controls", [e1, e2, e5]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("B", "Export controls China chips", [e2, e3, e5]),
            ], display_name="The AI Journal"),
            _make_entry("msg-3", "c@x.com", "Unusual Whales", [
                _make_idea("C", "China semiconductors chips", [e3, e4, e5]),
            ], display_name="Unusual Whales"),
        ]

        clusters = cluster_ideas(entries)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_pass_through_entries_are_ignored(self):
        """Pass-through entries should not participate in clustering."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")

        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg", is_pass_through=True),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]

        clusters = cluster_ideas(entries)
        assert len(clusters) == 0

    def test_entries_without_ideas_are_ignored(self):
        """Entries with ideas=None should not participate."""
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")

        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", ideas=None),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]

        clusters = cluster_ideas(entries)
        assert len(clusters) == 0

    def test_clusters_ranked_by_sender_count_then_size_and_capped(self):
        """Build 6 qualifying clusters; assert 5 returned in right order."""
        # Use distinct entity pairs for each cluster so they don't merge
        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        e3 = EntityMention(name="AI", entity_type="technology", sentiment="positive")
        e4 = EntityMention(name="chips", entity_type="technology", sentiment="positive")
        e5 = EntityMention(name="Fed", entity_type="institution", sentiment="neutral")
        e6 = EntityMention(name="rates", entity_type="policy", sentiment="neutral")
        e7 = EntityMention(name="China", entity_type="country", sentiment="neutral")
        e8 = EntityMention(name="trade", entity_type="policy", sentiment="negative")
        e9 = EntityMention(name="Apple", entity_type="company", sentiment="positive")
        e10 = EntityMention(name="earnings", entity_type="event", sentiment="positive")
        e11 = EntityMention(name="Tesla", entity_type="company", sentiment="negative")
        e12 = EntityMention(name="deliveries", entity_type="event", sentiment="negative")

        # Cluster 1: 4 senders, 4 ideas - entities (e1, e2)
        c1_entries = [
            _make_entry(f"msg-{i}", f"s{i}@x.com", f"Sender {i}", [
                _make_idea(f"Idea {i}", "Nvidia export controls", [e1, e2]),
            ], display_name=f"Sender {i}") for i in range(4)
        ]

        # Cluster 2: 3 senders, 3 ideas - entities (e3, e4)
        c2_entries = [
            _make_entry(f"msg-{i+4}", f"s{i+4}@x.com", f"Sender {i+4}", [
                _make_idea(f"Idea {i+4}", "AI chips advance", [e3, e4]),
            ], display_name=f"Sender {i+4}") for i in range(3)
        ]

        # Cluster 3: 2 senders, 4 ideas (2 ideas each) - entities (e5, e6)
        c3_entries = [
            _make_entry(f"msg-{i+7}", f"s{i+7}@x.com", f"Sender {i+7}", [
                _make_idea(f"Idea {i+7}a", "Fed rates move", [e5, e6]),
                _make_idea(f"Idea {i+7}b", "Rates decision", [e5, e6]),
            ], display_name=f"Sender {i+7}") for i in range(2)
        ]

        # Cluster 4: 2 senders, 3 ideas - entities (e7, e8)
        c4_entries = [
            _make_entry(f"msg-{i+11}", f"s{i+11}@x.com", f"Sender {i+11}", [
                _make_idea(f"Idea {i+11}", "China trade policy", [e7, e8]),
            ], display_name=f"Sender {i+11}") for i in range(3)
        ]

        # Cluster 5: 2 senders, 2 ideas - entities (e9, e10)
        c5_entries = [
            _make_entry(f"msg-{i+14}", f"s{i+14}@x.com", f"Sender {i+14}", [
                _make_idea(f"Idea {i+14}", "Apple earnings", [e9, e10]),
            ], display_name=f"Sender {i+14}") for i in range(2)
        ]

        # Cluster 6: 2 senders, 2 ideas - entities (e11, e12) (should be capped out)
        c6_entries = [
            _make_entry(f"msg-{i+16}", f"s{i+16}@x.com", f"Sender {i+16}", [
                _make_idea(f"Idea {i+16}", "Tesla deliveries", [e11, e12]),
            ], display_name=f"Sender {i+16}") for i in range(2)
        ]

        entries = c1_entries + c2_entries + c3_entries + c4_entries + c5_entries + c6_entries

        clusters = cluster_ideas(entries)
        assert len(clusters) == 5  # capped at _MAX_THEMES = 5
        # Order: 4 senders/4 ideas, 3 senders/3 ideas (earlier), 3 senders/3 ideas, 2 senders/4 ideas, 2 senders/2 ideas
        assert len(clusters[0]) == 4  # c1: 4 senders
        assert len(clusters[1]) == 3  # c2: 3 senders, 3 ideas, earlier
        assert len(clusters[2]) == 3  # c4: 3 senders, 3 ideas
        assert len(clusters[3]) == 4  # c3: 2 senders, 4 ideas
        assert len(clusters[4]) == 2  # c5: 2 senders, 2 ideas

    def test_empty_entries_return_empty_list(self):
        """Empty entries list returns empty clusters."""
        clusters = cluster_ideas([])
        assert clusters == []


# ---------------------------------------------------------------------------
# TestThemeSynthesizer
# ---------------------------------------------------------------------------

class TestThemeSynthesizer:
    """Tests for ThemeSynthesizer class (mocked API)."""

    def _setup_mock_response(self, mocker, response_text: str):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = response_text
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.synthesis.TokenBucketLimiter.acquire")
        mocker.patch("time.sleep")
        return mock_client

    def test_well_formed_response_becomes_theme_with_all_sources(self, mocker):
        """Valid TITLE/BODY/DISAGREEMENT response creates Theme with all sources."""
        response = (
            "TITLE: Nvidia hit by new export controls\n"
            "BODY: Bloomberg reports Nvidia faces new curbs while The AI Journal adds "
            "that China restrictions expand. Every source named.\n"
            "DISAGREEMENT: Bloomberg emphasizes revenue impact; The AI Journal focuses on supply chain."
        )
        self._setup_mock_response(mocker, response)

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        themes = synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert len(themes) == 1
        theme = themes[0]
        assert theme.title == "Nvidia hit by new export controls"
        assert "Bloomberg" in theme.sources
        assert "The AI Journal" in theme.sources
        assert theme.disagreement is not None
        assert "Bloomberg" in theme.disagreement
        assert theme.absorbed_idea_keys == (("msg-1", 0), ("msg-2", 0))

    def test_disagreement_none_maps_to_python_none(self, mocker):
        """DISAGREEMENT: NONE (case-insensitive) maps to None."""
        response = (
            "TITLE: Agreement story\n"
            "BODY: All sources agree on the facts.\n"
            "DISAGREEMENT: NONE"
        )
        self._setup_mock_response(mocker, response)

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        themes = synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert len(themes) == 1
        assert themes[0].disagreement is None

    def test_disagreement_text_is_kept(self, mocker):
        """Non-NONE disagreement text is preserved."""
        response = (
            "TITLE: Disagreement story\n"
            "BODY: Sources differ on details.\n"
            "DISAGREEMENT: Source A says X, Source B says Y."
        )
        self._setup_mock_response(mocker, response)

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        themes = synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert len(themes) == 1
        assert themes[0].disagreement == "Source A says X, Source B says Y."

    def test_missing_body_yields_no_theme(self, mocker):
        """Missing BODY line returns no theme."""
        response = "TITLE: Only title\nDISAGREEMENT: NONE"
        self._setup_mock_response(mocker, response)

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        themes = synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert len(themes) == 0

    def test_api_error_on_one_cluster_does_not_block_others(self, mocker):
        """API error on first cluster, success on second -> 1 theme, 4 create calls (3 retries + 1 success)."""
        mock_client = MagicMock()

        # First 3 calls fail (retries), 4th succeeds
        fail_response = MagicMock()
        fail_response.content = []

        success_response = MagicMock()
        success_content = MagicMock()
        success_content.type = "text"
        success_content.text = (
            "TITLE: Success theme\n"
            "BODY: This one worked.\n"
            "DISAGREEMENT: NONE"
        )
        success_response.content = [success_content]

        mock_client.messages.create.side_effect = [
            anthropic.APIError("API Error", request=MagicMock(), body=None),
            anthropic.APIError("API Error", request=MagicMock(), body=None),
            anthropic.APIError("API Error", request=MagicMock(), body=None),
            success_response,
        ]

        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.synthesis.TokenBucketLimiter.acquire")
        mocker.patch("time.sleep")

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
            _make_entry("msg-3", "c@x.com", "Unusual Whales", [
                _make_idea("Idea 3", "Another story", [e1, e2]),
            ], display_name="Unusual Whales"),
            _make_entry("msg-4", "d@x.com", "Kilo", [
                _make_idea("Idea 4", "Another story 2", [e1, e2]),
            ], display_name="Kilo"),
        ]
        # Two clusters, first fails, second succeeds
        clusters = [[("msg-1", 0), ("msg-2", 0)], [("msg-3", 0), ("msg-4", 0)]]

        themes = synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert len(themes) == 1
        assert themes[0].title == "Success theme"
        assert mock_client.messages.create.call_count == 4

    def test_rate_limiter_acquired_before_every_attempt(self, mocker):
        """Rate limiter acquire called before each API attempt."""
        mock_client = MagicMock()
        success_response = MagicMock()
        success_content = MagicMock()
        success_content.type = "text"
        success_content.text = "TITLE: X\nBODY: Y\nDISAGREEMENT: NONE"
        success_response.content = [success_content]
        mock_client.messages.create.return_value = success_response

        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mock_acquire = mocker.patch("agent.trends.synthesis.TokenBucketLimiter.acquire")
        mocker.patch("time.sleep")

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert mock_acquire.call_count == 1

    def test_user_message_labels_each_idea_with_its_source(self, mocker):
        """User message includes each source label and idea content."""
        captured_messages = []

        mock_client = MagicMock()
        success_response = MagicMock()
        success_content = MagicMock()
        success_content.type = "text"
        success_content.text = "TITLE: X\nBODY: Y\nDISAGREEMENT: NONE"
        success_response.content = [success_content]
        mock_client.messages.create.return_value = success_response

        def capture_create(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            return success_response

        mock_client.messages.create.side_effect = capture_create
        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.synthesis.TokenBucketLimiter.acquire")
        mocker.patch("time.sleep")

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1 title", "Idea 1 body", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2 title", "Idea 2 body", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert len(captured_messages) == 1
        user_msg = captured_messages[0][0]["content"]
        assert "--- Bloomberg ---" in user_msg
        assert "--- The AI Journal ---" in user_msg
        assert "Idea 1 title" in user_msg
        assert "Idea 1 body" in user_msg
        assert "Idea 2 title" in user_msg
        assert "Idea 2 body" in user_msg

    def test_thinking_block_before_text_is_handled(self, mocker):
        """Response with thinking block before text block is handled by extract_text."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # thinking block first
        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.text = "thinking..."
        # text block second
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "TITLE: X\nBODY: Y\nDISAGREEMENT: NONE"
        mock_response.content = [thinking_block, text_block]
        mock_client.messages.create.return_value = mock_response

        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.synthesis.TokenBucketLimiter.acquire")
        mocker.patch("time.sleep")

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        themes = synthesize_themes(clusters, entries, "test-key", model="claude-test")

        assert len(themes) == 1

    def test_uses_configured_model(self, mocker):
        """ThemeSynthesizer uses the model passed to it."""
        mock_client = MagicMock()
        success_response = MagicMock()
        success_content = MagicMock()
        success_content.type = "text"
        success_content.text = "TITLE: X\nBODY: Y\nDISAGREEMENT: NONE"
        success_response.content = [success_content]
        mock_client.messages.create.return_value = success_response

        mocker.patch("anthropic.Anthropic", return_value=mock_client)
        mocker.patch("agent.trends.synthesis.TokenBucketLimiter.acquire")
        mocker.patch("time.sleep")

        e1 = EntityMention(name="Nvidia", entity_type="company", sentiment="negative")
        e2 = EntityMention(name="export controls", entity_type="policy", sentiment="negative")
        entries = [
            _make_entry("msg-1", "a@x.com", "Bloomberg", [
                _make_idea("Idea 1", "Nvidia faces curbs", [e1, e2]),
            ], display_name="Bloomberg"),
            _make_entry("msg-2", "b@x.com", "AI Journal", [
                _make_idea("Idea 2", "Export controls expand", [e1, e2]),
            ], display_name="The AI Journal"),
        ]
        clusters = [[("msg-1", 0), ("msg-2", 0)]]

        synthesize_themes(clusters, entries, "test-key", model="custom-model-name")

        mock_client.messages.create.assert_called_once()
        assert mock_client.messages.create.call_args.kwargs["model"] == "custom-model-name"