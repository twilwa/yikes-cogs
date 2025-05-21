import re
from typing import Literal, Optional, NoReturn
import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box
import logging
import aiohttp
import asyncio
import os

log = logging.getLogger("red.yikescogs.twitterfix")

RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

DEFAULT_GUILD = {
    "enabled": False,  # Master switch for everything
    "openrouter_model": "",  # User-configurable model string
    "monitored_channels": [],  # Empty list means all channels
}

XCOM_REGEX = re.compile(r"https://x\.com/[^\s]+", re.IGNORECASE)

class TwitterFix(commands.Cog):
    """
    A cog that processes x.com links, posts r.jina.ai/xcancel.com links, and uses OpenRouter for summaries and thread titles.
    """

    def __init__(self, bot: Red) -> None:
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=315351812821745669,
            force_registration=True,
        )
        self.config.register_guild(**DEFAULT_GUILD)

    @commands.group(name="twitterfix")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def _twitterfix(self, ctx: commands.Context):
        """Configuration options for TwitterFix."""
        pass

    @_twitterfix.command(name="enable")
    async def _enable(self, ctx: commands.Context, true_or_false: bool):
        """Enable or disable the TwitterFix cog for this server."""
        if ctx.guild:
            await self.config.guild(ctx.guild).enabled.set(true_or_false)
            status = "enabled" if true_or_false else "disabled"
            await ctx.send(f"TwitterFix is now {status}.")

    @_twitterfix.command(name="setmodel")
    async def _setmodel(self, ctx: commands.Context, *, model: str):
        """Set the OpenRouter model string (provider/model:tag). Validates with a dummy call."""
        if not ctx.guild:
            return
        # Dummy validation: just check it's non-empty and contains a slash
        if not model or "/" not in model:
            await ctx.send("Model string must be in the format provider/model:tag.")
            return
        # TODO: Actually validate with OpenRouter API (dummy call)
        await self.config.guild(ctx.guild).openrouter_model.set(model)
        await ctx.send(f"OpenRouter model set to `{model}`.")

    @_twitterfix.command(name="showsettings")
    async def _show_settings(self, ctx: commands.Context):
        """Show the current settings for TwitterFix."""
        if not ctx.guild:
            return
        settings = await self.config.guild(ctx.guild).all()
        enabled = settings["enabled"]
        model = settings["openrouter_model"]
        channels = settings["monitored_channels"]
        channel_mentions = []
        if channels:
            for channel_id in channels:
                ch = ctx.guild.get_channel(channel_id)
                channel_mentions.append(
                    ch.mention if ch else f"Invalid ID: {channel_id}"
                )
            channel_str = (
                ", ".join(channel_mentions)
                if channel_mentions
                else "None (All channels active)"
            )
        else:
            channel_str = "None (All channels active)"
        embed = discord.Embed(
            title="TwitterFix Settings", color=await ctx.embed_color()
        )
        embed.add_field(name="Enabled", value=str(enabled), inline=True)
        embed.add_field(name="OpenRouter Model", value=model or "Not set", inline=False)
        embed.add_field(name="Monitored Channels", value=channel_str, inline=False)
        await ctx.send(embed=embed)

    @_twitterfix.group(name="channel")
    async def _channel(self, ctx: commands.Context):
        """
        Manage monitored channels.

        By default (when this list is empty), the bot monitors all channels.
        Adding channels here restricts monitoring ONLY to those specified.
        """
        pass

    @_channel.command(name="add")
    async def _channel_add(self, ctx: commands.Context, channel: discord.TextChannel):
        """Add a channel to the monitored list."""
        if ctx.guild:
            async with self.config.guild(ctx.guild).monitored_channels() as channels:
                if channel.id not in channels:
                    channels.append(channel.id)
                    await ctx.send(f"{channel.mention} will now be monitored.")
                else:
                    await ctx.send(f"{channel.mention} is already being monitored.")

    @_channel.command(name="remove")
    async def _channel_remove(self, ctx: commands.Context, channel: discord.TextChannel):
        """Remove a channel from the monitored list."""
        if ctx.guild:
            async with self.config.guild(ctx.guild).monitored_channels() as channels:
                if channel.id in channels:
                    channels.remove(channel.id)
                    await ctx.send(f"{channel.mention} will no longer be monitored.")
                    if not channels:
                        await ctx.send(
                            "No channels are specifically monitored. All channels are now active."
                        )
                else:
                    await ctx.send(f"{channel.mention} was not in the monitored list.")

    @_channel.command(name="clear")
    async def _channel_clear(self, ctx: commands.Context):
        """Clear the monitored channel list, making the bot monitor all channels."""
        if ctx.guild:
            await self.config.guild(ctx.guild).monitored_channels.set([])
            await ctx.send(
                "Monitored channel list cleared. The bot will now monitor all channels."
            )

    @_channel.command(name="list")
    async def _channel_list(self, ctx: commands.Context):
        """List the channels currently being monitored."""
        if not ctx.guild:
            return
        channels = await self.config.guild(ctx.guild).monitored_channels()
        if not channels:
            await ctx.send(
                "No channels are specifically monitored (the list is empty).\n"
                "**This means the bot is monitoring ALL channels.**"
            )
            return
        channel_mentions = []
        invalid_channels = []
        for channel_id in channels:
            ch = ctx.guild.get_channel(channel_id)
            if ch:
                channel_mentions.append(ch.mention)
            else:
                invalid_channels.append(channel_id)
        if channel_mentions:
            await ctx.send(
                f"Monitoring the following channels:\n{', '.join(channel_mentions)}"
            )
        else:
            await ctx.send("No valid channels are currently set for monitoring.")
        if invalid_channels:
            await ctx.send(
                f"Note: The following channel IDs are stored but could not be found (they may have been deleted): {', '.join(map(str, invalid_channels))}"
            )

    async def poll_markdown(self, url: str, max_attempts: int = 10, delay: float = 2.0) -> Optional[str]:
        """Poll the r.jina.ai URL for markdown content, return as string if found."""
        async with aiohttp.ClientSession() as session:
            for attempt in range(max_attempts):
                try:
                    async with session.get(url, headers={"Accept": "text/markdown"}) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            if text.strip():
                                return text
                except Exception as e:
                    log.warning(f"Error polling markdown ({url}): {e}")
                await asyncio.sleep(delay)
        return None

    async def call_openrouter(self, model: str, markdown: str) -> Optional['dict[str, str]']:
        """Send markdown to OpenRouter API and return structured output (dict) or None."""
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        prompt = (
            "You are a Discord thread summarizer. Given the following markdown, "
            "return a JSON object with two fields: 'thread-title' (a concise, descriptive title for the thread) "
            "and 'thread-summary' (a short summary of the content). Markdown follows:\n\n" + markdown
        )
        data = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 512,
        }
        headers = {}
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=data, headers=headers, timeout=60) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        # Try to extract the structured object from the response
                        content = result["choices"][0]["message"]["content"]
                        import json as _json
                        return _json.loads(content)
                    else:
                        log.error(f"OpenRouter API error: {resp.status} {await resp.text()}")
        except Exception as e:
            log.error(f"OpenRouter API call failed: {e}")
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        # Offload heavy work so we don't block the event loop
        self.bot.loop.create_task(self.process_message(message))

    async def process_message(self, message: discord.Message) -> None:
        try:
            if not message.guild:
                return
            if await self.bot.cog_disabled_in_guild(self, message.guild):
                return
            settings = await self.config.guild(message.guild).all()
            if not settings["enabled"]:
                return
            # Channel monitoring
            monitored_channels = settings.get("monitored_channels", [])
            if monitored_channels and message.channel.id not in monitored_channels:
                return
            # Look for x.com link
            match = XCOM_REGEX.search(message.content)
            if not match:
                return
            x_url = match.group(0)
            # Convert to xcancel.com for Discord message, use nitter.net for Jina
            xcancel_url = x_url.replace("x.com", "xcancel.com", 1)
            nitter_url = x_url.replace("x.com", "nitter.net", 1)
            jina_url = f"r.jina.ai/{nitter_url}"
            # Create thread if possible
            channel_perms = message.channel.permissions_for(message.guild.me)
            if not channel_perms.create_public_threads:
                return
            thread_title = f"Discussion for {x_url}"
            thread = await message.create_thread(name=thread_title[:100], auto_archive_duration=1440)
            botmsg = await thread.send(xcancel_url)  # Only post xcancel.com link
            # --- Async workflow: poll for markdown, call OpenRouter, update thread and message ---
            await asyncio.sleep(2)  # Give the link a moment to process
            markdown_url = f"https://{jina_url}"
            markdown = await self.poll_markdown(markdown_url)
            if not markdown:
                await thread.send("Could not retrieve markdown content for summarization.")
                return
            model = settings.get("openrouter_model")
            if not model:
                await thread.send("No OpenRouter model configured. Use the setmodel command.")
                return
            summary_obj = await self.call_openrouter(model, markdown)
            if not summary_obj:
                await thread.send("OpenRouter API failed to return a summary.")
                return
            # Update thread title and bot message
            new_title = summary_obj.get("thread-title")
            summary = summary_obj.get("thread-summary")
            if new_title:
                try:
                    await thread.edit(name=new_title[:100])
                except Exception as e:
                    log.warning(f"Failed to update thread title: {e}")
            if summary:
                try:
                    await botmsg.edit(content=f"{xcancel_url}\n\n{summary}")
                except Exception as e:
                    log.warning(f"Failed to edit bot message: {e}")
        except Exception as e:
            log.error(f"Failed to create thread or send message: {e}")
            return
        # --- Async workflow: poll for markdown, call OpenRouter, update thread and message ---
        markdown_url = f"https://{jina_url}"
        # Poll for readiness with exponential backoff
        delay = 0.5
        max_delay = 5.0
        markdown = None
        for attempt in range(5):
            markdown = await self.poll_markdown(markdown_url)
            if markdown:
                break
            log.debug(f"Polling attempt {attempt+1} failed, retrying in {delay} seconds")
            await asyncio.sleep(delay)
            delay = min(max_delay, delay * 2)
        if not markdown:
            await thread.send("Could not retrieve markdown content for summarization.")
            return
        model = settings.get("openrouter_model")
        if not model:
            await thread.send("No OpenRouter model configured. Use the setmodel command.")
            return
        summary_obj = await self.call_openrouter(model, markdown)
        if not summary_obj:
            await thread.send("OpenRouter API failed to return a summary.")
            return
        # Update thread title and bot message
        new_title = summary_obj.get("thread-title")
        summary = summary_obj.get("thread-summary")
        if new_title:
            try:
                await thread.edit(name=new_title[:100])
            except Exception as e:
                log.warning(f"Failed to update thread title: {e}")
        if summary:
            try:
                await botmsg.edit(content=f"{xcancel_url}\n\n{summary}")
            except Exception as e:
                log.warning(f"Failed to edit bot message: {e}")

    # The rest of the cog (message handling, etc.) will be implemented next.
