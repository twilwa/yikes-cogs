import re
from typing import Literal, Optional, NoReturn

import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

# Regex to find URLs, ensuring they start with http:// or https://
# and capture the domain and the rest of the path/query
URL_REGEX = re.compile(r"https?://([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^?\s]*)?(\?[^\s]*)?")

DEFAULT_GUILD = {
    "enabled": False,  # Master switch for everything
    "url_mapping_enabled": False,  # Controls URL mapping feature
    "title_updates_enabled": False,  # Controls thread title updating feature
    "monitored_channels": [],  # Empty list means all channels
    "url_map": {
        "twitter.com": "vxtwitter.com",
        "x.com": "vxtwitter.com",
    },
    "thread_title_format": "Discussion thread for {url}",
    "send_in_thread": True,  # Kept for potential future flexibility
}


class TwitterFix(commands.Cog):
    """
    A cog that fixes social media links and updates thread titles.
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
        # Dictionary to track threads that have already had their titles updated
        self.updated_threads = set()

    async def red_delete_data_for_user(
        self, *, requester: RequestType, user_id: int
    ) -> NoReturn:
        # This cog stores configuration per guild, not per user.
        # User data removal doesn't apply here.
        pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Serves two purposes:
        1. Processes embed messages in threads to update their titles
        2. Checks messages for URLs to create discussion threads
        """
        # First, handle thread title updates if title updates are enabled
        if isinstance(message.channel, discord.Thread) and message.channel.guild:
            # Check if thread title updates are enabled for this guild
            guild_settings = await self.config.guild(message.channel.guild).all()
            if (guild_settings["enabled"] and 
                guild_settings["title_updates_enabled"] and
                "https://" in message.channel.name and 
                message.channel.id not in self.updated_threads):
                
                # Check if message has embeds
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title:
                            # Found a title in an embed, update the thread name
                            try:
                                await message.channel.edit(name=embed.title[:100])  # Thread names limited to 100 chars
                                # Mark this thread as updated so we don't try again
                                self.updated_threads.add(message.channel.id)
                                break
                            except (discord.Forbidden, discord.HTTPException) as e:
                                print(f"TwitterFix: Failed to update thread title: {e}")
                                self.updated_threads.add(message.channel.id)
            return  # Don't process URL fixes for messages in threads

        # Standard URL processing logic follows
        if message.guild is None:  # Ignore DMs
            return
        if message.author.bot:  # Ignore bots
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if await self.bot.is_automod_immune(
            message.author
        ):  # Ignore automod immune users
            return

        guild_settings = await self.config.guild(message.guild).all()
        if not guild_settings["enabled"] or not guild_settings["url_mapping_enabled"]:
            return

        monitored_channels = guild_settings["monitored_channels"]
        # If monitored_channels is not empty, only check those channels
        if monitored_channels and message.channel.id not in monitored_channels:
            return

        content = message.content
        url_map = guild_settings["url_map"]
        found_url: Optional[str] = None
        modified_url: Optional[str] = None
        original_domain: Optional[str] = None

        # Find the first matching URL in the message
        for match in URL_REGEX.finditer(content):
            full_url = match.group(0)
            domain = match.group(1).lower()  # Domain part (e.g., twitter.com)
            path = match.group(2) or ""  # Path part (e.g., /user/status/123)
            query = match.group(3) or ""  # Query part (e.g., ?s=20)

            if domain in url_map:
                found_url = full_url
                original_domain = domain
                replacement_domain = url_map[domain]
                # Reconstruct the URL with the new domain
                modified_url = f"https://{replacement_domain}{path}{query}"
                break  # Process only the first found match

        if found_url and modified_url:
            # Check permissions
            channel_perms = message.channel.permissions_for(message.guild.me)
            if not channel_perms.create_public_threads:
                # Maybe log this or notify an admin channel? For now, just return.
                print(
                    f"TwitterFix: Missing 'Create Public Threads' permission in channel"
                )
                return

            thread_title = guild_settings["thread_title_format"].format(url=found_url)
            # Ensure title is within Discord limits (100 chars)
            thread_title = thread_title[:100]

            try:
                # Create the thread attached to the original message
                thread = await message.create_thread(
                    name=thread_title, auto_archive_duration=1440
                )  # 1 day archive
                
                # Send the modified URL into the thread
                await thread.send(modified_url)
            except discord.Forbidden:
                print(
                    f"TwitterFix: Failed to create thread or send message due to permissions"
                )
            except discord.HTTPException as e:
                print(f"TwitterFix: Failed to create thread or send message: {e}")

    # --- Configuration Commands ---

    @commands.group(name="twitterfix")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def _twitterfix(self, ctx: commands.Context):
        """Configuration options for TwitterFix."""
        pass

    @_twitterfix.command(name="enable")
    async def _enable(self, ctx: commands.Context, true_or_false: bool):
        """Enable or disable the TwitterFix cog entirely for this server."""
        if ctx.guild:
            await self.config.guild(ctx.guild).enabled.set(true_or_false)
            status = "enabled" if true_or_false else "disabled"
            await ctx.send(f"TwitterFix is now {status}.")
            
    @_twitterfix.command(name="enableurlmap")
    async def _enable_urlmap(self, ctx: commands.Context, true_or_false: bool):
        """Enable or disable just the URL mapping feature."""
        if ctx.guild:
            await self.config.guild(ctx.guild).url_mapping_enabled.set(true_or_false)
            status = "enabled" if true_or_false else "disabled"
            await ctx.send(f"URL mapping feature is now {status}.")
            
    @_twitterfix.command(name="enabletitleupdates")
    async def _enable_titleupdates(self, ctx: commands.Context, true_or_false: bool):
        """Enable or disable just the thread title update feature."""
        if ctx.guild:
            await self.config.guild(ctx.guild).title_updates_enabled.set(true_or_false)
            status = "enabled" if true_or_false else "disabled"
            await ctx.send(f"Thread title updates feature is now {status}.")
            
    @_twitterfix.command(name="clearcache")
    async def _clearcache(self, ctx: commands.Context):
        """Clear the cache of threads that have had their titles updated."""
        self.updated_threads.clear()
        await ctx.send("Thread title update cache has been cleared.")

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
    async def _channel_remove(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
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
            # Optional: Offer to clean up invalid IDs

    # --- URL Map Commands ---

    @_twitterfix.group(name="urlmap")
    async def _urlmap(self, ctx: commands.Context):
        """Manage the URL domain replacement mappings."""
        pass

    @_urlmap.command(name="add")
    async def _urlmap_add(
        self, ctx: commands.Context, original_domain: str, replacement_domain: str
    ):
        """
        Add or update a URL domain replacement.

        Example: [p]twitterfix urlmap add x.com vxtwitter.com
        """
        if not ctx.guild:
            return
            
        original_domain = original_domain.lower().strip("/")  # Normalize
        replacement_domain = replacement_domain.lower().strip("/")  # Normalize

        # Basic validation (not a full domain validator)
        if (
            "." not in original_domain
            or " " in original_domain
            or "://" in original_domain
        ):
            await ctx.send(
                f"Invalid format for original domain: `{original_domain}`. Please provide just the domain name (e.g., `x.com`)."
            )
            return
        if (
            "." not in replacement_domain
            or " " in replacement_domain
            or "://" in replacement_domain
        ):
            await ctx.send(
                f"Invalid format for replacement domain: `{replacement_domain}`. Please provide just the domain name (e.g., `vxtwitter.com`)."
            )
            return

        async with self.config.guild(ctx.guild).url_map() as url_map:
            url_map[original_domain] = replacement_domain

        await ctx.send(
            f"Mapping added: `{original_domain}` will now be replaced with `{replacement_domain}`."
        )

    @_urlmap.command(name="remove", aliases=["delete", "del"])
    async def _urlmap_remove(self, ctx: commands.Context, original_domain: str):
        """
        Remove a URL domain replacement mapping.

        Example: [p]twitterfix urlmap remove x.com
        """
        if not ctx.guild:
            return
            
        original_domain = original_domain.lower().strip("/")  # Normalize

        async with self.config.guild(ctx.guild).url_map() as url_map:
            if original_domain in url_map:
                del url_map[original_domain]
                await ctx.send(f"Mapping for `{original_domain}` removed.")
            else:
                await ctx.send(f"No mapping found for `{original_domain}`.")

    # --- Show Settings Command ---

    @_twitterfix.command(name="showsettings")
    async def _show_settings(self, ctx: commands.Context):
        """Show the current settings for TwitterFix."""
        if not ctx.guild:
            return
            
        settings = await self.config.guild(ctx.guild).all()
        master_enabled = settings["enabled"]
        url_mapping_enabled = settings["url_mapping_enabled"]
        title_updates_enabled = settings["title_updates_enabled"]
        channels = settings["monitored_channels"]
        url_map = settings["url_map"]
        title_format = settings["thread_title_format"]

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

        map_str = "\n".join(
            [f"- `{orig}` -> `{repl}`" for orig, repl in url_map.items()]
        )
        if not map_str:
            map_str = "No URL mappings configured."

        embed = discord.Embed(
            title="TwitterFix Settings", color=await ctx.embed_color()
        )
        
        # Show feature statuses
        embed.add_field(name="Master Switch", value=str(master_enabled), inline=True)
        embed.add_field(name="URL Mapping", value=str(url_mapping_enabled), inline=True)
        embed.add_field(name="Thread Title Updates", value=str(title_updates_enabled), inline=True)
        
        # Show other settings 
        embed.add_field(name="Monitored Channels", value=channel_str, inline=False)
        embed.add_field(name="URL Mappings", value=map_str, inline=False)
        embed.add_field(
            name="Thread Title Format", value=box(title_format), inline=False
        )

        await ctx.send(embed=embed)
