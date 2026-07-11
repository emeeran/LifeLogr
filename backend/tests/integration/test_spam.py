"""Tests for the local spam filter (scorer, blocklist, allowlist, bulk delete)."""

from app.models.email_account import EmailAccount
from app.models.email_folder import EmailFolder
from app.models.email_message import EmailMessage
from app.services.spam_service import SPAM_THRESHOLD, SpamService, score_message
from sqlalchemy import select


async def _seed_account_folder(db_session, label="acct", host="imap.example.com"):
    acct = EmailAccount(
        label=label,
        email_address="me@example.com",
        imap_host=host,
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="me",
        password_encrypted="x",
    )
    db_session.add(acct)
    await db_session.flush()
    folder = EmailFolder(account_id=acct.id, folder_name="INBOX", uidvalidity=1)
    db_session.add(folder)
    await db_session.flush()
    return acct, folder


def _msg(folder, account, frm, subject="hi", uid=1, snippet="hello"):
    return EmailMessage(
        account_id=account.id,
        folder_id=folder.id,
        uid=uid,
        from_address=frm,
        from_name=frm.split("@")[0],
        to_addresses=[{"address": "me@example.com", "name": None}],
        subject=subject,
        snippet=snippet,
        sent_at=None,
    )


class TestSpamScorer:
    def test_clean_mail_scores_low(self):
        s = score_message(
            "Project update — Q3 roadmap",
            "anna@acme-corp.com",
            "Anna Lee",
            "Hi team, attaching the updated roadmap for Q3. Let me know your thoughts.",
            None,
        )
        assert s < SPAM_THRESHOLD

    def test_obvious_spam_scores_high(self):
        s = score_message(
            "CONGRATULATIONS WINNER!!!",
            "promo@freemoney.xyz",
            "PayPal Security",
            "Click here for your FREE prize! Buy now. http://a http://b http://c http://d http://e",
            None,
        )
        assert s >= SPAM_THRESHOLD
        assert s == 1.0  # capped

    def test_suspicious_tld_alone_flagged(self):
        s = score_message("Hello", "someone@random.top", "Someone", "Just saying hi.", None)
        assert s >= 0.35

    def test_legit_newsletter_not_flagged(self):
        # 'unsubscribe' is NOT in the body word list, so a normal newsletter passes.
        s = score_message(
            "Your weekly digest",
            "news@reputable.com",
            "The Newsletter",
            "Here are this week's top stories. To unsubscribe, click the link.",
            None,
        )
        assert s < SPAM_THRESHOLD


class TestSpamClassify:
    async def test_contact_allowlist_keeps_ham(self, client, db_session):
        acct, folder = await _seed_account_folder(db_session)
        # Save the sender as a contact → allowlisted.
        await client.post("/api/v1/contacts", json={"email": "anna@acme.com", "name": "Anna"})
        # Even a spammy-looking message from a contact is not spam.
        db_session.add(
            _msg(
                folder,
                acct,
                "anna@acme.com",
                subject="WINNER!!!",
                snippet="claim your prize",
                uid=1,
            )
        )
        await db_session.commit()
        await client.post("/api/v1/email/spam/rescore")
        res = (await client.get("/api/v1/email/messages?spam_only=true")).json()
        assert not any(m["from_address"] == "anna@acme.com" for m in res["items"])

    async def test_blocklist_makes_spam(self, client, db_session):
        acct, folder = await _seed_account_folder(db_session)
        db_session.add(
            _msg(folder, acct, "promo@spammer.top", subject="deals", snippet="buy now", uid=2)
        )
        await db_session.commit()
        await client.post(
            "/api/v1/email/spam/rules", json={"pattern": "spammer.top", "is_domain": True}
        )
        await client.post("/api/v1/email/spam/rescore")
        spam = (await client.get("/api/v1/email/messages?spam_only=true")).json()
        assert any(m["from_address"] == "promo@spammer.top" for m in spam["items"])
        # Default listing hides spam.
        normal = (await client.get("/api/v1/email/messages")).json()
        assert not any(m["from_address"] == "promo@spammer.top" for m in normal["items"])

    async def test_list_exclude_spam_flag(self, client, db_session):
        acct, folder = await _seed_account_folder(db_session)
        m = _msg(folder, acct, "x@nobody.xyz", subject="FREE", snippet="click", uid=3)
        m.is_spam = True
        db_session.add(m)
        await db_session.commit()
        hidden = (await client.get("/api/v1/email/messages")).json()
        shown = (
            await client.get("/api/v1/email/messages?exclude_spam=false&spam_only=true")
        ).json()
        assert not any(i["id"] == m.id for i in hidden["items"])
        assert any(i["id"] == m.id for i in shown["items"])


class TestMarkSpamAndBulkDelete:
    async def test_mark_spam_creates_blocklist_rule(self, client, db_session):
        acct, folder = await _seed_account_folder(db_session)
        db_session.add(_msg(folder, acct, "noise@junk.stream", subject="hi", snippet="x", uid=10))
        await db_session.commit()
        mid = (
            (await db_session.execute(select(EmailMessage).where(EmailMessage.uid == 10)))
            .scalar_one()
            .id
        )
        patched = await client.patch(f"/api/v1/email/messages/{mid}/spam", json={"is_spam": True})
        assert patched.status_code == 200
        assert patched.json()["is_spam"] is True
        rules = (await client.get("/api/v1/email/spam/rules")).json()
        assert any(r["pattern"] == "junk.stream" and r["is_domain"] for r in rules)
        # Mark not-spam clears the rule.
        await client.patch(f"/api/v1/email/messages/{mid}/spam", json={"is_spam": False})
        rules2 = (await client.get("/api/v1/email/spam/rules")).json()
        assert not any(r["pattern"] == "junk.stream" for r in rules2)

    async def test_bulk_delete(self, client, db_session):
        acct, folder = await _seed_account_folder(db_session)
        db_session.add_all(
            [
                _msg(folder, acct, "a@x.com", uid=20),
                _msg(folder, acct, "b@x.com", uid=21),
            ]
        )
        await db_session.commit()
        ids = [r.id for r in (await db_session.execute(select(EmailMessage))).scalars().all()]
        assert len(ids) == 2
        res = await client.post("/api/v1/email/messages/bulk-delete", json=ids)
        assert res.status_code == 204
        remaining = (await client.get("/api/v1/email/messages?exclude_spam=false")).json()
        assert remaining["total"] == 0


class TestBlockSender:
    async def test_block_action_lookup(self, db_session):
        svc = SpamService(db_session)
        assert await svc.block_action("a@x.com", "x.com") is None
        await svc.add_rule("x.com", is_domain=True, action="delete")
        assert await svc.block_action("a@x.com", "x.com") == "delete"
        assert await svc.block_action("a@y.com", "y.com") is None

    async def _seed_three(self, db_session):
        acct, folder = await _seed_account_folder(db_session)
        db_session.add_all(
            [
                _msg(folder, acct, "noise@junk.stream", subject="a", snippet="x", uid=10),
                _msg(folder, acct, "other@junk.stream", subject="b", snippet="y", uid=11),
                _msg(folder, acct, "clean@good.com", subject="c", snippet="z", uid=12),
            ]
        )
        await db_session.commit()
        mid = (
            (await db_session.execute(select(EmailMessage).where(EmailMessage.uid == 10)))
            .scalar_one()
            .id
        )
        return mid

    async def test_block_junk_flags_all_from_domain(self, client, db_session):
        mid = await self._seed_three(db_session)
        res = await client.post(
            "/api/v1/email/messages/{}/block".format(mid),
            json={"action": "junk", "scope": "domain"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["action"] == "junk"
        assert body["affected"] == 2  # both junk.stream senders
        rules = (await client.get("/api/v1/email/spam/rules")).json()
        assert any(r["pattern"] == "junk.stream" and r["action"] == "junk" for r in rules)
        spam = (await client.get("/api/v1/email/messages?spam_only=true")).json()
        assert {m["from_address"] for m in spam["items"]} == {
            "noise@junk.stream",
            "other@junk.stream",
        }
        normal = (await client.get("/api/v1/email/messages")).json()
        assert {m["from_address"] for m in normal["items"]} == {"clean@good.com"}

    async def test_block_delete_removes_all_from_domain(self, client, db_session):
        mid = await self._seed_three(db_session)
        res = await client.post(
            "/api/v1/email/messages/{}/block".format(mid),
            json={"action": "delete", "scope": "domain"},
        )
        assert res.status_code == 200
        assert res.json()["affected"] == 2
        rules = (await client.get("/api/v1/email/spam/rules")).json()
        assert any(r["pattern"] == "junk.stream" and r["action"] == "delete" for r in rules)
        all_msgs = (await client.get("/api/v1/email/messages?exclude_spam=false")).json()
        assert {m["from_address"] for m in all_msgs["items"]} == {"clean@good.com"}

    async def test_block_sender_exact_address_scope(self, client, db_session):
        mid = await self._seed_three(db_session)
        # scope=sender blocks only the exact address, not the whole domain.
        res = await client.post(
            "/api/v1/email/messages/{}/block".format(mid),
            json={"action": "junk", "scope": "sender"},
        )
        assert res.status_code == 200
        assert res.json()["affected"] == 1
        rules = (await client.get("/api/v1/email/spam/rules")).json()
        assert any(r["pattern"] == "noise@junk.stream" and not r["is_domain"] for r in rules)
