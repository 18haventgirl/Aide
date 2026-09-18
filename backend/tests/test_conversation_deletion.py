"""Ensure deletion removes stored chat text and respects conversation ownership."""

import tempfile
import unittest
from pathlib import Path

from core.database_core.client import DatabaseClient
from core.database_core.config import DatabaseConfig
from service.models.chat_message import ChatMessage
from service.models.conversation import Conversation
from service.services.conversation_service import ConversationService


class ConversationDeletionTests(unittest.TestCase):
    def test_owned_conversation_deletion_removes_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            config = DatabaseConfig()
            config.db_type = "sqlite"
            config.sqlite_path = str(Path(directory) / "test.db")
            database = DatabaseClient(config)
            self.assertTrue(database.initialize())
            self.assertTrue(database.create_tables())
            service = ConversationService(database)
            with database.get_session() as session:
                conversation = Conversation(user_id=7, id_str="medical-test", title="研究测试")
                session.add(conversation)
                session.flush()
                session.add(ChatMessage(conversation_id=conversation.id, conversation_id_str="medical-test",
                                        sender_type="human", content="合成健康问题"))
                session.commit()
            self.assertFalse(service.delete_conversation_by_id_str("medical-test", user_id=8))
            with database.get_session() as session:
                self.assertEqual(session.query(ChatMessage).count(), 1)
            self.assertTrue(service.delete_conversation_by_id_str("medical-test", user_id=7))
            with database.get_session() as session:
                self.assertEqual(session.query(Conversation).count(), 0)
                self.assertEqual(session.query(ChatMessage).count(), 0)
            database.close()


if __name__ == "__main__":
    unittest.main()
