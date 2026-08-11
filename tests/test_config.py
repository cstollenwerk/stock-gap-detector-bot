import os
import unittest
from unittest.mock import patch

from stock_gap_detector.config import DiscordConfig, database_url_from_env


class ConfigTests(unittest.TestCase):
    def test_database_url_can_be_built_from_discrete_env_fields(self):
        with patch.dict(
            os.environ,
            {
                "STOCK_GAP_DETECTOR_DB_HOST": "pi-server.local",
                "STOCK_GAP_DETECTOR_DB_PORT": "5432",
                "STOCK_GAP_DETECTOR_DB_NAME": "candle_db",
                "STOCK_GAP_DETECTOR_DB_USER": "candle_user",
                "STOCK_GAP_DETECTOR_DB_PASSWORD": "pa:ss@word",
                "STOCK_GAP_DETECTOR_CANDLE_DB_URL": "postgresql://ignored",
            },
            clear=True,
        ):
            self.assertEqual(
                database_url_from_env(),
                "postgresql://candle_user:pa%3Ass%40word@pi-server.local:5432/candle_db",
            )

    def test_database_url_falls_back_to_url_env(self):
        with patch.dict(
            os.environ,
            {"STOCK_GAP_DETECTOR_CANDLE_DB_URL": "postgresql://example/candle_db"},
            clear=True,
        ):
            self.assertEqual(database_url_from_env(), "postgresql://example/candle_db")

    def test_database_host_defaults_to_localhost_when_parts_are_set(self):
        with patch.dict(
            os.environ,
            {
                "STOCK_GAP_DETECTOR_DB_NAME": "candle_db",
                "STOCK_GAP_DETECTOR_DB_USER": "candle_user",
                "STOCK_GAP_DETECTOR_DB_PASSWORD": "secret",
            },
            clear=True,
        ):
            self.assertEqual(
                database_url_from_env(),
                "postgresql://candle_user:secret@localhost:5432/candle_db",
            )

    def test_discord_config_reads_token_and_channel(self):
        with patch.dict(
            os.environ,
            {
                "STOCK_GAP_DETECTOR_DISCORD_TOKEN": "token",
                "STOCK_GAP_DETECTOR_DISCORD_CHANNEL_ID": "123",
                "STOCK_GAP_DETECTOR_DISCORD_GUILD_ID": "456",
            },
            clear=True,
        ):
            config = DiscordConfig.from_env()

        self.assertEqual(config.token, "token")
        self.assertEqual(config.channel_id, 123)
        self.assertEqual(config.guild_id, 456)


if __name__ == "__main__":
    unittest.main()
