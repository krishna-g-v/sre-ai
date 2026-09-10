"""Live chat-conversation tests against the real backend + Postgres + LLM. See README.md
in this directory before running these.

These exist specifically to catch query-orchestration/context regressions like the one
that prompted this suite: a short follow-up ("ad uid it is") got misclassified as
off-topic/general and answered with a hallucinated guess instead of using the pinned
document and conversation history. See docs/08-chat-sessions-and-orchestration.md and the
history-handling change in app/agents/orchestrator.py.

Structure: `conversation` gives each test its own real chat session against the real
`engg_onboarding.pdf`, uploaded fresh (see conftest.py) so these never depend on
whatever's already sitting in someone's knowledge base.
"""

import pytest

pytestmark = pytest.mark.e2e


def _answer(turn: dict) -> str:
    return turn["message"]["content"]


def _category(turn: dict) -> str:
    return turn["message"]["message_category"]


def assert_mentions(turn: dict, *phrases: str, msg: str = "") -> None:
    answer = _answer(turn).lower()
    for phrase in phrases:
        assert phrase.lower() in answer, f"{msg or 'expected phrase missing'}: {phrase!r} not in answer:\n{_answer(turn)}"


def assert_not_mentions(turn: dict, *phrases: str, msg: str = "") -> None:
    answer = _answer(turn).lower()
    for phrase in phrases:
        assert phrase.lower() not in answer, f"{msg or 'unexpected/hallucinated phrase present'}: {phrase!r} in answer:\n{_answer(turn)}"


class TestGeneralChat:
    """Regression coverage for: general chat should be near-eliminated. A bare greeting
    gets a short reply, not a fabricated bullet-point menu of "things I can help with" —
    the assistant doesn't actually know the KB's contents well enough to promise that."""

    def test_greeting_stays_general_and_does_not_touch_the_kb(self, conversation):
        turn = conversation.say("hi")
        assert _category(turn) == "general"
        assert turn["drifted"] is False
        assert turn["retrieved_titles"] == []

    def test_greeting_reply_is_short_with_no_fabricated_menu(self, conversation):
        turn = conversation.say("hi")
        answer = _answer(turn)
        assert len(answer) < 300, f"greeting reply should be a short sentence, got {len(answer)} chars: {answer!r}"
        assert "*" not in answer and "\n-" not in answer, f"greeting reply should not be a bullet list: {answer!r}"

    def test_statement_without_a_question_still_triggers_document_grounding(self, conversation):
        """The exact reported bug: "I am a new joinee" (a statement, not phrased as a
        question) got classified as general and answered with a generic, fabricated
        "welcome to the team, what do you need help with" menu instead of real content."""
        turn = conversation.say("i am a new joinee")
        assert _category(turn) == "document_topic", (
            f"a statement with real content must not be classified general: {_answer(turn)!r}"
        )
        assert turn["retrieved_titles"], "expected this to trigger a real knowledge-base lookup"
        assert_not_mentions(
            turn,
            "job responsibilities",
            "team and colleagues",
            "technical setup",
            msg="this is the exact fabricated menu pattern that was reported",
        )


class TestDocumentGroundingAndAutoPin:
    def test_onboarding_question_pins_the_right_document(self, conversation):
        message = "I'm a new joiner on the SRE team, what are the onboarding norms?"
        turn = conversation.say(message)
        assert _category(turn) == "document_topic"
        assert turn["retrieved_titles"], "expected the onboarding doc to be retrieved"
        assert turn["session"]["status"] == "pinned"
        # Title is the conversation's first message (ChatGPT/Claude-style), truncated to
        # a max length — not the document name, and pinning must not overwrite it.
        assert message.startswith(turn["session"]["title"].rstrip("…"))
        assert turn["session"]["pinned_document_title"] == "Engineering Onboarding Guide"

    def test_specific_fact_jenkins_url(self, conversation):
        turn = conversation.say("What's the URL for the primary Jenkins instance?")
        assert_mentions(turn, "jenkins.domain.com")

    def test_never_names_the_source_document(self, conversation):
        turn = conversation.say("What are the required AD groups for onboarding?")
        assert_not_mentions(
            turn,
            "engg_onboarding",
            ".pdf",
            "onboarding guide",
            "onboarding document",
            msg="the source document must never be named/described in the answer text",
        )

    def test_specific_fact_escalation_contact(self, conversation):
        turn = conversation.say("Who do I contact if my Bitbucket access isn't working?")
        assert_mentions(turn, "SCM Administration")

    def test_specific_fact_ad_propagation_time(self, conversation):
        turn = conversation.say("How long does it take for new AD group membership to take effect?")
        # Doc says "15 minutes to 4 hours" — a specific enough number that a hallucinated
        # answer is very unlikely to land on both by chance.
        assert_mentions(turn, "15 minutes")
        assert_mentions(turn, "4 hours")


class TestConversationalContext:
    """Regression coverage for the exact bug reported: short, context-dependent
    follow-ups getting misread as off-topic (false drift) or answered with zero context
    (hallucination) because only the latest message was ever looked at."""

    def test_reported_conversation_ad_uid_followups(self, conversation):
        conversation.say("hi")
        t2 = conversation.say("i am a new joinee in SRE team, tell me the norms")
        assert _category(t2) == "document_topic"

        t3 = conversation.say("i got my ad id, what next?")
        assert t3["drifted"] is False, f"false-positive drift on an on-topic follow-up: {_answer(t3)!r}"
        assert "start a new chat session" not in _answer(t3).lower()
        assert_mentions(t3, "group", msg="expected the AD-groups next-step content")

        t4 = conversation.say("ad uid it is")
        assert t4["drifted"] is False, f"false-positive drift on an on-topic follow-up: {_answer(t4)!r}"
        assert_not_mentions(t4, "ldap", msg="this exact hallucination is what prompted this test")
        # Real continuations here could reasonably stay on AD-account verification (login/
        # password/MFA) or move on to AD groups — either is grounded; only check that it's
        # clearly still the same onboarding thread, not requiring one specific phrasing.
        answer = _answer(t4).lower()
        assert any(kw in answer for kw in ("group", "mfa", "password", "login", "verif")), (
            f"answer doesn't look like a grounded continuation of the AD UID conversation: {_answer(t4)!r}"
        )

    def test_context_dependent_pronoun_followup(self, conversation):
        """A second, different short-follow-up scenario (not the exact reported one) so
        the fix is verified to generalize, not just special-cased for the AD UID example."""
        conversation.say("What do I need to do to get Jenkins access?")
        t2 = conversation.say("and the SSV one?")
        assert t2["drifted"] is False
        assert_mentions(t2, "ssv-jenkins.domain.com")

    def test_single_word_followup_stays_on_topic(self, conversation):
        conversation.say("Tell me about the required AD groups for onboarding.")
        t2 = conversation.say("grafana?")
        assert t2["drifted"] is False
        assert_mentions(t2, "grafana")


class TestDriftDetection:
    def test_genuinely_unrelated_technical_question_does_not_fabricate_onboarding_facts(self, conversation):
        conversation.say("i am a new joinee in SRE team, tell me the norms")
        t2 = conversation.say("explain the steps for a blue-green deployment strategy")
        # However it gets categorized, it must not answer a deployment-strategy question
        # by inventing onboarding-specific facts that have nothing to do with it.
        assert_not_mentions(t2, "ad uid", "jenkins.domain.com", msg="cross-contamination from the pinned document")


class TestNoHallucinationOnUnknownFacts:
    def test_fact_not_in_document_is_not_fabricated(self, conversation):
        conversation.say("i am a new joinee in SRE team, tell me the norms")
        turn = conversation.say("what is the office wifi password?")
        # The document never mentions a wifi password — a real answer here (any specific
        # string presented as *the* password) would be a fabrication by definition.
        assert_not_mentions(turn, "wifi password is", "the password is")
