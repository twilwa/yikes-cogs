import re
from typing import Literal, Optional

import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

# Regex to find URLs, ensuring they start with http:// or https://
# and capture the domain and the rest of the path/query
URL_REGEX = re.compile(r"https?://([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^?\s]*)?(\?[^\s]*)?")

DEFAULT_GUILD = {
    "enabled": False,
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
    a simple url fixer
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=315351812821745669,
            force_registration=True,
        )
        self.config.register_guild(**DEFAULT_GUILD)

    async def red_delete_data_for_user(
        self, *, requester: RequestType, user_id: int
    ) -> None:
        # This cog stores configuration per guild, not per user.
        # User data removal doesn't apply here.
        super().red_delete_data_for_user(requester=requester, user_id=user_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Checks messages for specified URLs and creates a discussion thread."""
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
        if not guild_settings["enabled"]:
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
                    f"TwitterFix: Missing 'Create Public Threads' permission in {message.channel.name} ({message.guild.name})"
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
                    f"TwitterFix: Failed to create thread or send message due to permissions in {message.channel.name} ({message.guild.name})"
                )
            except discord.HTTPException as e:
                print(f"TwitterFix: Failed to create thread or send message: {e}")

    # --- Configuration Commands ---

    @commands.group(name="twitterfixset", aliases=["tfixset"])
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def _twitterfixset(self, ctx: commands.Context):
        """Configuration options for TwitterFix."""
        pass

    @_twitterfixset.command(name="enable")
    async def _enable(self, ctx: commands.Context, true_or_false: bool):
        """Enable or disable the TwitterFix cog for this server."""
        await self.config.guild(ctx.guild).enabled.set(true_or_false)
        status = "enabled" if true_or_false else "disabled"
        await ctx.send(f"TwitterFix is now {status}.")

    @_twitterfixset.group(name="channel")
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
        await self.config.guild(ctx.guild).monitored_channels.set([])
        await ctx.send(
            "Monitored channel list cleared. The bot will now monitor all channels."
        )

    @_channel.command(name="list")
    async def _channel_list(self, ctx: commands.Context):
        """List the channels currently being monitored."""
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

    @_twitterfixset.group(name="urlmap")
    async def _urlmap(self, ctx: commands.Context):
        """Manage the URL domain replacement mappings."""
        pass

    @_urlmap.command(name="add")
    async def _urlmap_add(
        self, ctx: commands.Context, original_domain: str, replacement_domain: str
    ):
        """
        Add or update a URL domain replacement.

        Example: [p]twitterfixset urlmap add x.com vxtwitter.com
        """
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

        Example: [p]twitterfixset urlmap remove x.com
        """
        original_domain = original_domain.lower().strip("/")  # Normalize

        async with self.config.guild(ctx.guild).url_map() as url_map:
            if original_domain in url_map:
                del url_map[original_domain]
                await ctx.send(f"Mapping for `{original_domain}` removed.")
            else:
                await ctx.send(f"No mapping found for `{original_domain}`.")

    # --- Show Settings Command ---

    @_twitterfixset.command(name="showsettings")
    async def _show_settings(self, ctx: commands.Context):
        """Show the current settings for TwitterFix."""
        settings = await self.config.guild(ctx.guild).all()
        enabled = settings["enabled"]
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
        embed.add_field(name="Enabled", value=str(enabled), inline=True)
        embed.add_field(name="Monitored Channels", value=channel_str, inline=False)
        embed.add_field(name="URL Mappings", value=map_str, inline=False)
        embed.add_field(
            name="Thread Title Format", value=box(title_format), inline=False
        )

        await ctx.send(embed=embed)
