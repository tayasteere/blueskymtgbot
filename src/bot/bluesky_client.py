from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from atproto import models


@dataclass
class Mention:
    uri: str
    cid: str
    text: str
    root_uri: str
    root_cid: str
    author_did: str
    parent_uri: str = ""
    parent_cid: str = ""
    reason: str = "mention"


@dataclass
class PostRef:
    uri: str
    cid: str


# Opaque blob reference returned by atproto's upload_blob — passed through to embeds.
BlobRef = Any


class StateStore(Protocol):
    def load(self) -> str | None: ...
    def save(self, last_seen_at: str) -> None: ...


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class BlueskyClient:
    def __init__(self, agent: Any, state_store: StateStore | None = None) -> None:
        self._agent = agent
        self._state_store = state_store
        loaded = state_store.load() if state_store else None
        # Default to now so a cold start skips all pre-existing notifications.
        self._last_seen_at: str = loaded if loaded is not None else _now_iso()

    def login(self, identifier: str, password: str) -> None:
        self._agent.login(identifier, password)

    def get_new_mentions(self) -> list[Mention]:
        response = self._agent.app.bsky.notification.list_notifications(
            params={"limit": 50}
        )
        notifications = response.notifications

        new_mentions = [
            n
            for n in notifications
            if n.reason in ("mention", "reply") and n.indexed_at > self._last_seen_at
        ]

        # Advance cursor to the most recent notification seen this poll.
        if notifications:
            latest = notifications[0]
            if latest.indexed_at > self._last_seen_at:
                self._last_seen_at = latest.indexed_at
                if self._state_store:
                    self._state_store.save(self._last_seen_at)

        return [self._to_mention(n) for n in new_mentions]

    def _to_mention(self, notification: Any) -> Mention:
        record = notification.record
        text = record.text or ""
        if record.reply:
            root_uri = record.reply.root.uri
            root_cid = record.reply.root.cid
            parent_uri = record.reply.parent.uri
            parent_cid = record.reply.parent.cid
        else:
            root_uri = notification.uri
            root_cid = notification.cid
            parent_uri = ""
            parent_cid = ""
        return Mention(
            uri=notification.uri,
            cid=notification.cid,
            text=text,
            root_uri=root_uri,
            root_cid=root_cid,
            author_did=notification.author.did,
            parent_uri=parent_uri,
            parent_cid=parent_cid,
            reason=notification.reason,
        )

    def fetch_blocked_dids(self) -> set[str]:
        blocked: set[str] = set()
        cursor: str | None = None
        while True:
            params: dict = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = self._agent.app.bsky.graph.get_blocks(params=params)
            for profile in response.blocks:
                blocked.add(profile.did)
            cursor = getattr(response, "cursor", None)
            if not cursor:
                break
        return blocked

    def block_user(self, did: str) -> None:
        self._agent.com.atproto.repo.create_record(
            models.ComAtprotoRepoCreateRecord.Data(
                repo=self._agent.me.did,
                collection="app.bsky.graph.block",
                record=models.AppBskyGraphBlock.Record(
                    subject=did,
                    created_at=_now_iso(),
                ),
            )
        )

    def upload_image(self, data: bytes, mime_type: str) -> BlobRef:  # noqa: ARG002
        response = self._agent.upload_blob(data)
        return response.blob

    def reply_to_mention(
        self,
        mention: Mention,
        text: str,
        image: dict[str, Any] | None = None,
    ) -> PostRef:
        StrongRef = models.ComAtprotoRepoStrongRef.Main
        reply = models.AppBskyFeedPost.ReplyRef(
            parent=StrongRef(uri=mention.uri, cid=mention.cid),
            root=StrongRef(uri=mention.root_uri, cid=mention.root_cid),
        )
        embed = None
        if image:
            embed = models.AppBskyEmbedImages.Main(
                images=[
                    models.AppBskyEmbedImages.Image(
                        alt=image["alt"],
                        image=image["blob"],
                        aspect_ratio=models.AppBskyEmbedDefs.AspectRatio(
                            # Scryfall "normal" images are 745×1040
                            width=745,
                            height=1040,
                        ),
                    )
                ]
            )
        result = self._agent.send_post(text=text, reply_to=reply, embed=embed)
        return PostRef(uri=result.uri, cid=result.cid)

    def reply_in_thread(
        self,
        root: PostRef,
        parent: PostRef,
        text: str,
    ) -> PostRef:
        reply = models.AppBskyFeedPost.ReplyRef(
            parent=models.ComAtprotoRepoStrongRef.Main(uri=parent.uri, cid=parent.cid),
            root=models.ComAtprotoRepoStrongRef.Main(uri=root.uri, cid=root.cid),
        )
        result = self._agent.send_post(text=text, reply_to=reply)
        return PostRef(uri=result.uri, cid=result.cid)
