"""ABOUTME: Tests TwitterFix article rendering and fallback fetch helpers.
ABOUTME: Stubs Discord and Redbot imports so helper logic can run standalone."""

import sys
import types
import unittest
from importlib import util
from pathlib import Path


def command_decorator(*_args, **_kwargs):
    def decorate(func):
        func.command = command_decorator
        func.group = command_decorator
        return func

    return decorate


class Cog:
    @staticmethod
    def listener():
        return command_decorator()


class TextChannel:
    pass


class Message:
    pass


def install_import_stubs():
    discord = types.ModuleType("discord")
    discord.Embed = object
    discord.Message = Message
    discord.TextChannel = TextChannel
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientConnectorError = Exception

    commands = types.ModuleType("commands")
    commands.Cog = Cog
    commands.Context = object
    commands.group = command_decorator
    commands.guild_only = command_decorator

    checks = types.ModuleType("checks")
    checks.admin_or_permissions = command_decorator

    config = types.SimpleNamespace(get_conf=lambda *_args, **_kwargs: None)
    bot = types.ModuleType("bot")
    bot.Red = object

    chat_formatting = types.ModuleType("chat_formatting")
    chat_formatting.box = lambda value: value

    redbot = types.ModuleType("redbot")
    core = types.ModuleType("core")
    core.commands = commands
    core.Config = config
    core.checks = checks
    core.bot = bot
    utils = types.ModuleType("utils")
    utils.chat_formatting = chat_formatting
    core.utils = utils
    redbot.core = core

    sys.modules.setdefault("discord", discord)
    sys.modules.setdefault("aiohttp", aiohttp)
    sys.modules.setdefault("redbot", redbot)
    sys.modules.setdefault("redbot.core", core)
    sys.modules.setdefault("redbot.core.commands", commands)
    sys.modules.setdefault("redbot.core.checks", checks)
    sys.modules.setdefault("redbot.core.bot", bot)
    sys.modules.setdefault("redbot.core.utils", utils)
    sys.modules.setdefault("redbot.core.utils.chat_formatting", chat_formatting)


def load_twitterfix_module():
    install_import_stubs()
    module_path = Path(__file__).with_name("twitterfix.py")
    spec = util.spec_from_file_location("twitterfix_module", module_path)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TwitterFixArticleReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_article_reader_fetch_uses_detected_article_url_path(self):
        module = load_twitterfix_module()
        cog = module.TwitterFix.__new__(module.TwitterFix)
        requested_urls = []

        async def poll_markdown(url):
            requested_urls.append(url)
            return "article body"

        cog.poll_markdown = poll_markdown

        result = await cog.fetch_x_article_reader_markdown(
            "https://x.com/example/status/12345",
            "https://x.com/i/article/98765",
        )

        self.assertEqual(
            requested_urls,
            ["https://r.jina.ai/http://x-reader.val.run/i/article/98765"],
        )
        self.assertIn("Original post: https://x.com/example/status/12345", result)
        self.assertIn("Article URL: https://x.com/i/article/98765", result)
        self.assertIn("article body", result)


if __name__ == "__main__":
    unittest.main()
