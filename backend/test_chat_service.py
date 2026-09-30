from __future__ import annotations

import asyncio
import sys
import unittest
import uuid

from sqlalchemy import delete, select

from app.db.models import AgentRun, Message, User
from app.db.repositories.auth import AuthRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.session import AsyncSessionFactory, close_db
from app.services.chat import (
    ChatService,
    ChatWorkflowError,
    ConversationNotFoundError,
    InvalidChatMessageError,
)
from pipeline.agents.context import (
    ContextBuilder,
    ConversationContext,
    ConversationRole,
    PendingClarification,
)
from pipeline.agents.schemas import (
    AgentResponse,
    AgentResponseType,
    Citation,
    ClarificationField,
    ClarificationRequest,
    EvidenceSource,
    ExecutionPlan,
    Intent,
    RequirementLevel,
    RetrievalMode,
    TaskStatus,
    ToolName,
    ToolObservation,
    ReasonerOutput,
)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class DeterministicWorkflow:
    def __init__(
        self,
        *,
        conversation_id: uuid.UUID,
        fail: bool = False,
        degraded: bool = False,
        clarify: bool = False,
    ) -> None:
        self.conversation_id = conversation_id
        self.fail = fail
        self.degraded = degraded
        self.clarify = clarify
        self.context_builder = ContextBuilder(max_recent_messages=12)
        self.calls: list[tuple[str, ConversationContext]] = []
        self.service_session = None
        self.transaction_open_during_run: bool | None = None
        self.initial_run_status: str | None = None

    async def run(
        self,
        query: str,
        *,
        context: ConversationContext | None = None,
    ) -> dict:
        context = context or ConversationContext()
        self.calls.append((query, context.model_copy(deep=True)))
        self.transaction_open_during_run = (
            self.service_session.in_transaction()
            if self.service_session is not None
            else None
        )

        async with AsyncSessionFactory() as verify_session:
            result = await verify_session.execute(
                select(AgentRun)
                .where(AgentRun.conversation_id == self.conversation_id)
                .order_by(AgentRun.created_at.desc())
                .limit(1)
            )
            self.initial_run_status = result.scalar_one().status

        if self.fail:
            raise RuntimeError("provider secret details must not persist")

        plan = ExecutionPlan(
            intent=Intent.ITINERARY,
            goal="Build a deterministic itinerary",
            retrieval_mode=RetrievalMode.MIXED,
        )
        final_context = self.context_builder.append_message(
            context,
            role=ConversationRole.USER,
            content=query,
        )

        if self.clarify:
            request = ClarificationRequest(
                question="Bạn dự định đi bao nhiêu ngày?",
                fields=[
                    ClarificationField(
                        key="duration_days",
                        question="Bạn dự định đi bao nhiêu ngày?",
                        requirement=RequirementLevel.BLOCKING,
                    )
                ],
            )
            plan = plan.model_copy(update={"clarification": request})
            response = AgentResponse(
                response_type=AgentResponseType.CLARIFICATION,
                clarification=request,
                intent=Intent.ITINERARY,
            )
            final_context = self.context_builder.append_message(
                final_context,
                role=ConversationRole.ASSISTANT,
                content=request.question,
            ).model_copy(
                update={
                    "pending_clarification": PendingClarification(
                        original_query=query,
                        original_goal=plan.goal,
                        original_intent=plan.intent,
                        request=request,
                    )
                }
            )
        else:
            response = AgentResponse(
                answer="Lịch trình thử nghiệm đã sẵn sàng.",
                citations=[
                    Citation(
                        citation_id="citation-1",
                        evidence_id="evidence-1",
                        title="Nguồn du lịch",
                        url="https://example.com/travel",
                        source_type=EvidenceSource.WEB,
                    ),
                    Citation(
                        citation_id="citation-2",
                        task_id="weather-1",
                        title="Dữ liệu thời tiết",
                        url=None,
                        source_type=EvidenceSource.WEATHER,
                        tool=ToolName.WEATHER,
                    ),
                ],
                intent=Intent.ITINERARY,
                used_tools=[ToolName.WEATHER],
                degraded=self.degraded,
            )
            final_context = self.context_builder.append_message(
                final_context,
                role=ConversationRole.ASSISTANT,
                content=response.answer,
            )

        return {
            "plan": plan,
            "response": response,
            "conversation_context": final_context,
            "retry_count": 1,
            "observations": [
                ToolObservation(
                    task_id="weather-1",
                    tool=ToolName.WEATHER,
                    status=TaskStatus.SUCCESS,
                ),
                ToolObservation(
                    task_id="weather-2",
                    tool=ToolName.WEATHER,
                    status=TaskStatus.SUCCESS,
                ),
            ],
            "reasoner_output": ReasonerOutput(
                answer_type="itinerary",
                answer_goal="Provide a grounded answer",
                warnings=["Dự báo có thể thay đổi."],
                limitations=["Hãy kiểm tra lại trước khi đi."],
                degraded=self.degraded,
            ),
        }


class ChatServiceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.test_id = uuid.uuid4().hex
        self.email_prefix = f"chat-service-{self.test_id}"

        async with AsyncSessionFactory.begin() as session:
            auth = AuthRepository(session)
            conversations = ConversationRepository(session)
            self.owner = await auth.create_user(
                email=f"{self.email_prefix}-owner@example.com"
            )
            self.other_user = await auth.create_user(
                email=f"{self.email_prefix}-other@example.com"
            )
            self.conversation = await conversations.create_conversation(
                user_id=self.owner.id
            )
            self.owner_id = self.owner.id
            self.other_user_id = self.other_user.id
            self.conversation_id = self.conversation.id

    async def asyncTearDown(self) -> None:
        async with AsyncSessionFactory.begin() as session:
            await session.execute(
                delete(User).where(User.email.like(f"{self.email_prefix}%"))
            )
        await close_db()

    async def test_success_persists_turn_metadata_and_title(self) -> None:
        workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id
        )
        async with AsyncSessionFactory() as session:
            workflow.service_session = session
            service = ChatService(session, workflow)
            result = await service.send_message(
                user_id=self.owner_id,
                conversation_id=self.conversation_id,
                content="  Lập lịch trình Đà Lạt ba ngày  ",
            )

            self.assertEqual(len(workflow.calls), 1)
            self.assertEqual(
                workflow.calls[0][0],
                "Lập lịch trình Đà Lạt ba ngày",
            )
            self.assertEqual(workflow.calls[0][1].recent_messages, [])
            self.assertFalse(workflow.transaction_open_during_run)
            self.assertEqual(workflow.initial_run_status, "running")

            self.assertEqual(result.user_message.role, "user")
            self.assertEqual(result.user_message.sequence_no, 1)
            self.assertEqual(result.assistant_message.sequence_no, 2)
            self.assertEqual(result.agent_run.status, "success")
            self.assertEqual(
                result.agent_run.user_message_id,
                result.user_message.id,
            )
            self.assertEqual(
                result.agent_run.assistant_message_id,
                result.assistant_message.id,
            )
            self.assertIsNotNone(result.agent_run.completed_at)
            self.assertGreaterEqual(result.agent_run.latency_ms, 0)
            self.assertEqual(result.agent_run.intent, "ITINERARY")
            self.assertEqual(result.agent_run.retrieval_mode, "MIXED")
            self.assertEqual(result.agent_run.retry_count, 1)
            self.assertEqual(result.agent_run.tools_used, ["weather"])
            self.assertEqual(len(result.assistant_message.citations), 2)
            self.assertIsNone(result.assistant_message.citations[1]["url"])
            self.assertEqual(
                result.assistant_message.warnings,
                [
                    "Dự báo có thể thay đổi.",
                    "Hãy kiểm tra lại trước khi đi.",
                ],
            )

            conversation = await service.repository.get_conversation_by_id(
                self.conversation_id,
                self.owner_id,
            )
            self.assertEqual(
                conversation.title,
                "Lập lịch trình Đà Lạt ba ngày",
            )
            self.assertIsNotNone(conversation.context_state)

    async def test_non_owner_and_invalid_messages_write_nothing(self) -> None:
        workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id
        )
        async with AsyncSessionFactory() as session:
            service = ChatService(session, workflow)
            with self.assertRaises(ConversationNotFoundError):
                await service.send_message(
                    user_id=self.other_user_id,
                    conversation_id=self.conversation_id,
                    content="Xin chào",
                )
            with self.assertRaises(InvalidChatMessageError):
                await service.send_message(
                    user_id=self.owner_id,
                    conversation_id=self.conversation_id,
                    content="   ",
                )

            messages = await service.repository.list_messages(
                self.conversation_id,
                self.owner_id,
            )
            runs = await service.repository.list_agent_runs_for_conversation(
                self.conversation_id,
                self.owner_id,
            )
            self.assertEqual(messages, [])
            self.assertEqual(runs, [])
            self.assertEqual(workflow.calls, [])

    async def test_history_is_chronological_and_current_turn_not_duplicated(
        self,
    ) -> None:
        async with AsyncSessionFactory.begin() as seed_session:
            repository = ConversationRepository(seed_session)
            conversation = await repository.get_conversation_by_id(
                self.conversation_id,
                self.owner_id,
            )
            await repository.update_conversation_title(
                conversation,
                "Existing title",
            )
            await repository.add_message(
                conversation_id=self.conversation_id,
                role="user",
                content="Lập lịch Đà Lạt",
            )
            await repository.add_message(
                conversation_id=self.conversation_id,
                role="assistant",
                content="Bạn dự định đi bao nhiêu ngày?",
            )

        workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id
        )
        async with AsyncSessionFactory() as session:
            service = ChatService(session, workflow)
            result = await service.send_message(
                user_id=self.owner_id,
                conversation_id=self.conversation_id,
                content="  3 ngày  ",
            )

            prior = workflow.calls[0][1].recent_messages
            self.assertEqual(
                [(item.role.value, item.content) for item in prior],
                [
                    ("user", "Lập lịch Đà Lạt"),
                    ("assistant", "Bạn dự định đi bao nhiêu ngày?"),
                ],
            )
            self.assertNotIn("3 ngày", [item.content for item in prior])
            self.assertEqual(result.user_message.sequence_no, 3)
            self.assertEqual(result.assistant_message.sequence_no, 4)

            conversation = await service.repository.get_conversation_by_id(
                self.conversation_id,
                self.owner_id,
            )
            self.assertEqual(conversation.title, "Existing title")

    async def test_degraded_response_is_usable_and_persisted(self) -> None:
        workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id,
            degraded=True,
        )
        async with AsyncSessionFactory() as session:
            result = await ChatService(session, workflow).send_message(
                user_id=self.owner_id,
                conversation_id=self.conversation_id,
                content="Gợi ý lịch trình",
            )
            self.assertEqual(result.agent_run.status, "degraded")
            self.assertTrue(result.assistant_message.content)

    async def test_workflow_failure_keeps_user_turn_and_failed_run(self) -> None:
        workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id,
            fail=True,
        )
        async with AsyncSessionFactory() as session:
            service = ChatService(session, workflow)
            with self.assertRaises(ChatWorkflowError):
                await service.send_message(
                    user_id=self.owner_id,
                    conversation_id=self.conversation_id,
                    content="Thực hiện yêu cầu này",
                )

            messages = await service.repository.list_messages(
                self.conversation_id,
                self.owner_id,
            )
            runs = await service.repository.list_agent_runs_for_conversation(
                self.conversation_id,
                self.owner_id,
            )
            self.assertEqual(len(workflow.calls), 1)
            self.assertEqual([(item.role, item.content) for item in messages], [
                ("user", "Thực hiện yêu cầu này")
            ])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].status, "failed")
            self.assertIsNotNone(runs[0].completed_at)
            self.assertGreaterEqual(runs[0].latency_ms, 0)
            self.assertEqual(runs[0].error_code, "WORKFLOW_ERROR")
            self.assertEqual(
                runs[0].error_message,
                "Travel workflow execution failed",
            )
            self.assertNotIn("provider secret", runs[0].error_message)

    async def test_pending_context_survives_new_service_instance(self) -> None:
        first_workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id,
            clarify=True,
        )
        async with AsyncSessionFactory() as first_session:
            first = await ChatService(
                first_session,
                first_workflow,
            ).send_message(
                user_id=self.owner_id,
                conversation_id=self.conversation_id,
                content="Lập lịch Đà Lạt",
            )
            self.assertEqual(first.agent_run.status, "success")
            self.assertEqual(
                first.assistant_message.content,
                "Bạn dự định đi bao nhiêu ngày?",
            )

        second_workflow = DeterministicWorkflow(
            conversation_id=self.conversation_id
        )
        async with AsyncSessionFactory() as second_session:
            await ChatService(
                second_session,
                second_workflow,
            ).send_message(
                user_id=self.owner_id,
                conversation_id=self.conversation_id,
                content="3 ngày",
            )

            restored = second_workflow.calls[0][1]
            self.assertIsNotNone(restored.pending_clarification)
            self.assertEqual(
                restored.pending_clarification.original_query,
                "Lập lịch Đà Lạt",
            )
            self.assertEqual(
                [item.content for item in restored.recent_messages],
                [
                    "Lập lịch Đà Lạt",
                    "Bạn dự định đi bao nhiêu ngày?",
                ],
            )


if __name__ == "__main__":
    unittest.main()
