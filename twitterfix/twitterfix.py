"""ABOUTME: Discord cog that expands X/Twitter links into discussion threads.
ABOUTME: Fetches tweet/article markdown and summarizes it through OpenRouter."""

import re
import json
from typing import Literal, Optional, NoReturn
from urllib.parse import urlsplit
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
XCANCEL_ARTICLE_REGEX = re.compile(r"https://x\.com/i/article/\d+", re.IGNORECASE)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    )
}

class TwitterFix(commands.Cog):
    """
    A cog that processes x.com links, fetches tweet content via fxtwitter API, and uses OpenRouter for summaries and thread titles.
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
        self.recently_processed_messages = set() # For debouncing on_message

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
            log.info(f"TwitterFix enabled set to {true_or_false} in guild {ctx.guild.id} by {ctx.author.name}")
            await ctx.send(f"TwitterFix is now {status}.")

    @_twitterfix.command(name="setmodel")
    async def _setmodel(self, ctx: commands.Context, *, model: str):
        """Set the OpenRouter model string (provider/model:tag). Validates with a dummy call."""
        if not ctx.guild:
            return
        if not model or "/" not in model: # Basic format check
            await ctx.send("Model string must be in the format provider/model:tag (e.g., `openai/gpt-3.5-turbo`).")
            return
        
        await self.config.guild(ctx.guild).openrouter_model.set(model)
        log.info(f"OpenRouter model set to `{model}` in guild {ctx.guild.id} by {ctx.author.name}")
        await ctx.send(f"OpenRouter model set to `{model}`.")

    @_twitterfix.command(name="showsettings")
    async def _show_settings(self, ctx: commands.Context):
        """Show the current settings for TwitterFix."""
        if not ctx.guild:
            return
        settings = await self.config.guild(ctx.guild).all()
        enabled = settings.get("enabled", False)
        model = settings.get("openrouter_model", "Not set")
        monitored_channels_ids = settings.get("monitored_channels", [])
        
        channel_mentions = []
        if monitored_channels_ids:
            for channel_id in monitored_channels_ids:
                ch = ctx.guild.get_channel(channel_id)
                channel_mentions.append(ch.mention if ch else f"Invalid ID: {channel_id}")
            channel_str = ", ".join(channel_mentions) if channel_mentions else "None (All channels active)"
        else:
            channel_str = "All channels active"
            
        embed = discord.Embed(title="TwitterFix Settings", color=await ctx.embed_color())
        embed.add_field(name="Enabled", value=str(enabled), inline=True)
        embed.add_field(name="OpenRouter Model", value=f"`{model}`" if model != "Not set" else "Not set", inline=False)
        embed.add_field(name="Monitored Channels", value=channel_str, inline=False)
        await ctx.send(embed=embed)

    @_twitterfix.group(name="channel")
    async def _channel(self, ctx: commands.Context):
        """Manage monitored channels."""
        pass

    @_channel.command(name="add")
    async def _channel_add(self, ctx: commands.Context, channel: discord.TextChannel):
        """Add a channel to the monitored list."""
        if ctx.guild:
            async with self.config.guild(ctx.guild).monitored_channels() as channels:
                if channel.id not in channels:
                    channels.append(channel.id)
                    log.info(f"Channel {channel.id} added to monitored list in guild {ctx.guild.id} by {ctx.author.name}")
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
                    log.info(f"Channel {channel.id} removed from monitored list in guild {ctx.guild.id} by {ctx.author.name}")
                    await ctx.send(f"{channel.mention} will no longer be monitored.")
                    if not channels:
                        await ctx.send("No channels are specifically monitored. All channels are now active.")
                else:
                    await ctx.send(f"{channel.mention} was not in the monitored list.")

    @_channel.command(name="clear")
    async def _channel_clear(self, ctx: commands.Context):
        """Clear the monitored channel list, making the bot monitor all channels."""
        if ctx.guild:
            await self.config.guild(ctx.guild).monitored_channels.set([])
            log.info(f"Monitored channel list cleared in guild {ctx.guild.id} by {ctx.author.name}")
            await ctx.send("Monitored channel list cleared. The bot will now monitor all channels.")

    @_channel.command(name="list")
    async def _channel_list(self, ctx: commands.Context):
        """List the channels currently being monitored."""
        if not ctx.guild:
            return
        monitored_channels_ids = await self.config.guild(ctx.guild).monitored_channels()
        if not monitored_channels_ids:
            await ctx.send("No channels are specifically monitored (the list is empty).\n**This means the bot is monitoring ALL channels.**")
            return
        channel_mentions = []
        invalid_channels = []
        for channel_id in monitored_channels_ids:
            ch = ctx.guild.get_channel(channel_id)
            if ch:
                channel_mentions.append(ch.mention)
            else:
                invalid_channels.append(str(channel_id))
        if channel_mentions:
            mentions_str = ", ".join(channel_mentions)
            await ctx.send(f"Monitoring the following channels:\n{mentions_str}")
        else:
            await ctx.send("No valid channels are currently set for monitoring (all were invalid IDs).")
        if invalid_channels:
            invalids_str = ", ".join(invalid_channels)
            await ctx.send(f"Note: The following channel IDs are stored but could not be found (they may have been deleted): {invalids_str}")

    async def _remove_id_after_delay(self, msg_id: int, delay: int = 60):
        await asyncio.sleep(delay)
        self.recently_processed_messages.discard(msg_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if message.id in self.recently_processed_messages:
            log.info(f"Duplicate on_message event for message ID {message.id}, ignoring.")
            return
        
        self.recently_processed_messages.add(message.id)
        self.bot.loop.create_task(self._remove_id_after_delay(message.id))

        log.debug(f"Scheduling process_message for message ID {message.id}")
        self.bot.loop.create_task(self.process_message(message))

    async def process_message(self, message: discord.Message) -> None:
        try:
            if not message.guild: # Should be redundant due to guild_only on commands, but good for listeners
                return
            if await self.bot.cog_disabled_in_guild(self, message.guild):
                return
            
            settings = await self.config.guild(message.guild).all()
            if not settings.get("enabled", False):
                log.debug(f"Cog not enabled in guild {message.guild.id}. Skipping.")
                return
            
            monitored_channels = settings.get("monitored_channels", [])
            if monitored_channels and message.channel.id not in monitored_channels:
                log.debug(f"Channel {message.channel.id} not in monitored list for guild {message.guild.id}. Skipping.")
                return
            
            match = XCOM_REGEX.search(message.content)
            if not match:
                return
            
            x_url = match.group(0)
            log.info(f"Processing x.com URL: {x_url} in guild {message.guild.id}")

            xcancel_url = x_url.replace("x.com", "xcancel.com", 1)

            channel_perms = message.channel.permissions_for(message.guild.me)
            if not channel_perms.create_public_threads:
                log.warning(f"Missing 'Create Public Threads' permission in channel {message.channel.id}, guild {message.guild.id}.")
                return

            thread_title = f"Discussion for {x_url}"
            thread = await message.create_thread(name=thread_title[:100], auto_archive_duration=1440)
            botmsg = await thread.send(xcancel_url)
            log.debug(f"Created thread {thread.id} and sent initial message {botmsg.id}.")

            # --- Fetch tweet content: try fxtwitter API first (fast), fall back to Jina ---
            markdown_content = await self.fetch_fxtwitter(x_url)

            if not markdown_content:
                article_url = await self.find_xcancel_article_url(xcancel_url)
                if article_url:
                    log.info(f"Detected X article via xcancel for {x_url}: {article_url}")
                    markdown_content = await self.fetch_x_article_reader_markdown(x_url, article_url)
            
            if not markdown_content:
                log.info(f"fxtwitter failed, trying Jina fallback for {x_url}")
                nitter_url = x_url.replace("x.com", "nitter.net", 1)
                markdown_url = f"https://r.jina.ai/{nitter_url}"
                
                poll_delay = 0.5
                max_poll_delay = 5.0
                for attempt in range(5):
                    log.debug(f"Polling attempt {attempt + 1} for {markdown_url}")
                    markdown_content = await self.poll_markdown(markdown_url)
                    if markdown_content:
                        log.info(f"Successfully fetched markdown from {markdown_url}")
                        break
                    log.debug(f"Polling attempt {attempt + 1} failed for {markdown_url}, retrying in {poll_delay} seconds")
                    await asyncio.sleep(poll_delay)
                    poll_delay = min(max_poll_delay, poll_delay * 2)
            
            if not markdown_content:
                log.warning(f"Could not retrieve content for {x_url} from fxtwitter or Jina.")
                await thread.send("Could not retrieve tweet content for summarization.")
                return

            openrouter_model = settings.get("openrouter_model")
            if not openrouter_model:
                log.warning(f"No OpenRouter model configured in guild {message.guild.id}.")
                await thread.send("No OpenRouter model configured. Use the setmodel command.")
                return

            summary_obj = await self.call_openrouter(openrouter_model, markdown_content)
            if not summary_obj:
                log.warning(f"OpenRouter API call failed or returned no summary for model {openrouter_model}.")
                await thread.send("OpenRouter API failed to return a summary.")
                return
            
            log.info(f"Received summary from OpenRouter: {summary_obj}")

            new_thread_title = summary_obj.get("thread-title")
            summary_text = summary_obj.get("thread-summary")

            if new_thread_title:
                try:
                    await thread.edit(name=new_thread_title[:100])
                    log.debug(f"Updated thread {thread.id} title to: {new_thread_title[:100]}")
                except Exception as e:
                    log.warning(f"Failed to update thread title for {thread.id}: {e}")
            
            if summary_text:
                try:
                    await botmsg.edit(content=f"{xcancel_url}\n\n{summary_text}")
                    log.debug(f"Edited bot message {botmsg.id} in thread {thread.id} with summary.")
                except Exception as e:
                    log.warning(f"Failed to edit bot message {botmsg.id}: {e}")

        except Exception as e:
            log.error(f"Unhandled error in process_message for message {message.id} in guild {message.guild.id if message.guild else 'N/A'}: {e}", exc_info=True)

    async def fetch_fxtwitter(self, x_url: str) -> Optional[str]:
        """Fetch tweet content from fxtwitter API and return parsed markdown-like content."""
        api_url = x_url.replace("x.com", "api.fxtwitter.com", 1)
        api_url = api_url.split("?")[0]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=15, headers=DEFAULT_HEADERS) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tweet = data.get("tweet", {})
                        if not tweet:
                            log.warning(f"fxtwitter API returned no tweet data for {api_url}")
                            return None

                        article_markdown = self.render_fxtwitter_article(tweet)
                        if article_markdown:
                            author = tweet.get("author", {})
                            log.info(
                                "Successfully fetched article content from fxtwitter: @%s",
                                author.get("screen_name", "unknown"),
                            )
                            return article_markdown
                        
                        author = tweet.get("author", {})
                        author_name = author.get("name", "Unknown")
                        author_handle = author.get("screen_name", "unknown")
                        text = tweet.get("text", "")
                        if not text:
                            raw_text = tweet.get("raw_text", {})
                            if isinstance(raw_text, dict):
                                raw_text_value = raw_text.get("text", "")
                                if raw_text_value and not raw_text_value.startswith("https://t.co/"):
                                    text = raw_text_value
                        if not text.strip():
                            log.info(f"fxtwitter returned no usable tweet text for {api_url}")
                            return None
                        likes = tweet.get("likes", 0)
                        retweets = tweet.get("retweets", 0)
                        replies = tweet.get("replies", 0)
                        views = tweet.get("views", 0)
                        created_at = tweet.get("created_at", "")
                        replying_to = tweet.get("replying_to", "")
                        
                        content_parts = [
                            f"# Tweet by @{author_handle} ({author_name})",
                            f"\n{text}",
                        ]
                        
                        if replying_to:
                            content_parts.insert(1, f"\n> Replying to @{replying_to}")
                        
                        content_parts.append(f"\n---\n💬 {replies} | 🔁 {retweets} | ❤️ {likes} | 👁️ {views}")
                        if created_at:
                            content_parts.append(f"\n📅 {created_at}")
                        
                        log.info(f"Successfully fetched tweet from fxtwitter: @{author_handle}")
                        return "\n".join(content_parts)
                    else:
                        log.warning(f"fxtwitter API returned status {resp.status} for {api_url}")
                        return None
        except asyncio.TimeoutError:
            log.warning(f"fxtwitter API timed out for {api_url}")
        except Exception as e:
            log.warning(f"fxtwitter API error for {api_url}: {e}")
        return None

    def render_fxtwitter_article(self, tweet: dict) -> Optional[str]:
        article = tweet.get("article") or {}
        content = article.get("content") or {}
        blocks = content.get("blocks") or []
        title = (article.get("title") or "").strip()
        preview_text = (article.get("preview_text") or "").strip()
        if not title and not preview_text and not blocks:
            return None

        author = tweet.get("author", {})
        author_name = author.get("name", "Unknown")
        author_handle = author.get("screen_name", "unknown")
        article_id = article.get("id")
        article_url = f"https://x.com/i/article/{article_id}" if article_id else None
        body = self.render_x_article_blocks(content, article.get("media_entities") or [])
        likes = tweet.get("likes", 0)
        retweets = tweet.get("retweets", 0)
        replies = tweet.get("replies", 0)
        views = tweet.get("views", 0)
        created_at = tweet.get("created_at", "")

        content_parts = [f"# X Article by @{author_handle} ({author_name})"]
        if title:
            content_parts.append(f"\n## {title}")
        if preview_text and not body.startswith(preview_text):
            content_parts.append(f"\n{preview_text}")
        if body:
            content_parts.append(f"\n{body}")
        if article_url:
            content_parts.append(f"\nArticle URL: {article_url}")
        content_parts.append(f"\nOriginal post: {tweet.get('url', '')}")
        content_parts.append(f"\n---\n💬 {replies} | 🔁 {retweets} | ❤️ {likes} | 👁️ {views}")
        if created_at:
            content_parts.append(f"\n📅 {created_at}")
        return "\n".join(part for part in content_parts if part)

    def render_x_article_blocks(self, content: dict, media_entities: list[dict]) -> str:
        entity_lookup = self.build_entity_lookup(content.get("entityMap") or [])
        media_lookup = self.build_media_lookup(media_entities)
        rendered_blocks: list[str] = []

        for block in content.get("blocks") or []:
            block_type = block.get("type", "unstyled")
            raw_text = block.get("text", "")
            text = self.apply_article_entities(raw_text, block.get("entityRanges") or [], entity_lookup).strip()
            if block_type == "atomic":
                media_markdown = self.render_article_media_block(block, entity_lookup, media_lookup)
                if media_markdown:
                    rendered_blocks.append(media_markdown)
                continue
            if not text:
                continue

            if block_type == "header-one":
                rendered_blocks.append(f"# {text}")
            elif block_type == "header-two":
                rendered_blocks.append(f"## {text}")
            elif block_type == "header-three":
                rendered_blocks.append(f"### {text}")
            elif block_type == "unordered-list-item":
                rendered_blocks.append(f"- {text}")
            elif block_type == "ordered-list-item":
                rendered_blocks.append(f"1. {text}")
            elif block_type == "blockquote":
                rendered_blocks.append(f"> {text}")
            else:
                rendered_blocks.append(text)

        return "\n\n".join(rendered_blocks)

    def build_entity_lookup(self, entity_map: list | dict) -> dict[str, dict]:
        if isinstance(entity_map, dict):
            return {str(key): value for key, value in entity_map.items()}
        lookup = {}
        for item in entity_map:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if key is not None and isinstance(value, dict):
                lookup[str(key)] = value
        return lookup

    def build_media_lookup(self, media_entities: list[dict]) -> dict[str, str]:
        lookup = {}
        for media in media_entities:
            if not isinstance(media, dict):
                continue
            media_id = str(media.get("media_id", ""))
            media_info = media.get("media_info") or {}
            original_img_url = media_info.get("original_img_url")
            if media_id and original_img_url:
                lookup[media_id] = original_img_url
        return lookup

    def apply_article_entities(self, text: str, entity_ranges: list[dict], entity_lookup: dict[str, dict]) -> str:
        rendered = text
        for entity_range in sorted(entity_ranges, key=lambda item: item.get("offset", 0), reverse=True):
            offset = entity_range.get("offset", 0)
            length = entity_range.get("length", 0)
            key = str(entity_range.get("key"))
            entity = entity_lookup.get(key) or {}
            entity_type = entity.get("type")
            entity_data = entity.get("data") or {}
            span = rendered[offset:offset + length]
            replacement = span
            if entity_type == "LINK" and entity_data.get("url"):
                replacement = f"[{span}]({entity_data['url']})"
            rendered = rendered[:offset] + replacement + rendered[offset + length:]
        return rendered

    def render_article_media_block(
        self,
        block: dict,
        entity_lookup: dict[str, dict],
        media_lookup: dict[str, str],
    ) -> Optional[str]:
        for entity_range in block.get("entityRanges") or []:
            key = str(entity_range.get("key"))
            entity = entity_lookup.get(key) or {}
            if entity.get("type") != "MEDIA":
                continue
            media_items = (entity.get("data") or {}).get("mediaItems") or []
            urls = []
            for media_item in media_items:
                media_id = str(media_item.get("mediaId", ""))
                media_url = media_lookup.get(media_id)
                if media_url:
                    urls.append(media_url)
            if urls:
                return "\n".join(f"![Article image]({url})" for url in urls)
        return None

    async def find_xcancel_article_url(self, xcancel_url: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
                async with session.get(xcancel_url, timeout=15, allow_redirects=True) as resp:
                    text = await resp.text()
                    match = XCANCEL_ARTICLE_REGEX.search(text)
                    if match:
                        return match.group(0)
                    if "Verifying your request" in text:
                        log.debug(f"xcancel anti-bot page blocked article detection for {xcancel_url}")
        except asyncio.TimeoutError:
            log.warning(f"xcancel article detection timed out for {xcancel_url}")
        except Exception as e:
            log.warning(f"xcancel article detection failed for {xcancel_url}: {e}")
        return None

    async def fetch_x_article_reader_markdown(self, x_url: str, article_url: str) -> Optional[str]:
        path = urlsplit(x_url).path.lstrip("/")
        markdown_url = f"https://r.jina.ai/http://x-reader.val.run/{path}"
        markdown_content = await self.poll_markdown(markdown_url)
        if not markdown_content:
            return None
        return (
            "# X Article\n\n"
            f"Original post: {x_url}\n"
            f"Article URL: {article_url}\n\n"
            f"{markdown_content}"
        )

    async def poll_markdown(self, url: str, max_attempts: int = 10, delay: float = 2.0) -> Optional[str]:
        """Poll the r.jina.ai URL for markdown content, return as string if found."""
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            for attempt in range(max_attempts):
                try:
                    log.debug(f"poll_markdown attempt {attempt + 1} for {url}")
                    async with session.get(url, headers={"Accept": "text/markdown"}) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            if text.strip():
                                log.debug(f"poll_markdown success for {url}")
                                return text
                            else:
                                log.debug(f"poll_markdown for {url} returned empty content, status {resp.status}")
                        else:
                            log.warning(f"poll_markdown for {url} failed with status {resp.status}")
                except Exception as e:
                    log.warning(f"Exception during poll_markdown attempt for {url}: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(delay)
        log.warning(f"poll_markdown failed for {url} after {max_attempts} attempts.")
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
            "max_tokens": 512, # Increased max_tokens slightly for safety, can be tuned
        }
        headers = {}
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            log.warning("OPENROUTER_API_KEY not found in environment variables.")
            # Potentially return or raise here if API key is mandatory

        try:
            log.debug(f"Calling OpenRouter API ({api_url}) with model {model}.")
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=data, headers=headers, timeout=60) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        content_str = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if not content_str:
                            log.error(f"OpenRouter response missing expected content structure. Result: {result}")
                            return None
                        
                        # Try direct JSON parsing first
                        try:
                            structured_output = json.loads(content_str)
                            log.debug(f"OpenRouter API success, got: {structured_output}")
                            return structured_output
                        except json.JSONDecodeError:
                            # If direct parsing fails, try to extract JSON from markdown code blocks
                            log.debug(f"Direct JSON parsing failed, attempting to extract from markdown")
                            
                            # Pattern to match JSON in markdown code blocks
                            json_pattern = re.compile(r'```(?:json)?\s*(\{[^`]+\})\s*```', re.DOTALL)
                            match = json_pattern.search(content_str)
                            
                            if match:
                                json_str = match.group(1)
                                try:
                                    structured_output = json.loads(json_str)
                                    log.debug(f"Successfully extracted JSON from markdown: {structured_output}")
                                    return structured_output
                                except json.JSONDecodeError:
                                    log.debug(f"Failed to parse extracted JSON, trying fallback")
                            
                            # Fallback: Try to extract thread-title and thread-summary using regex
                            # This handles malformed JSON or partial responses
                            title_pattern = re.compile(r'"thread-title"\s*:\s*"([^"]+)"')
                            summary_pattern = re.compile(r'"thread-summary"\s*:\s*"([^"]+)"', re.DOTALL)
                            
                            title_match = title_pattern.search(content_str)
                            summary_match = summary_pattern.search(content_str)
                            
                            if title_match or summary_match:
                                structured_output = {}
                                if title_match:
                                    structured_output["thread-title"] = title_match.group(1)
                                if summary_match:
                                    # Handle all standard escape sequences in summary
                                    summary = summary_match.group(1)
                                    try:
                                        summary = json.loads(f'"{summary}"')
                                    except Exception:
                                        # Fallback to original if decoding fails
                                        pass
                                    structured_output["thread-summary"] = summary
                                log.info(f"Extracted data using regex fallback: {structured_output}")
                                return structured_output
                            
                            log.error(f"Failed to decode JSON from OpenRouter response. Content was: {content_str}")
                            return None
                    else:
                        error_text = await resp.text()
                        log.error(f"OpenRouter API error: {resp.status} - {error_text}")
        except asyncio.TimeoutError:
            log.error(f"OpenRouter API call timed out after 60 seconds for model {model}.")
        except aiohttp.ClientConnectorError as conn_e:
            log.error(f"OpenRouter API connection error: {conn_e}")
        except Exception as e:
            log.error(f"OpenRouter API call failed with unexpected error: {e}", exc_info=True)
        return None

    # The rest of the cog (message handling, etc.) will be implemented next.
