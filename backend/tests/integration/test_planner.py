"""Integration tests for the Planner module (tasks, subtasks, recurring events)."""

from datetime import datetime, timedelta


class TestPlannerTasks:
    async def test_list_task_subtask_complete(self, client):
        # Create a list
        lst = (await client.post("/api/v1/planner/lists", json={"name": "Work"})).json()
        assert lst["id"]

        # Top-level task
        task = (
            await client.post(
                "/api/v1/planner/tasks",
                json={"title": "Ship feature", "list_id": lst["id"], "priority": "high"},
            )
        ).json()
        assert task["id"]

        # Subtask
        sub = (
            await client.post(
                "/api/v1/planner/tasks",
                json={"title": "Write tests", "parent_id": task["id"]},
            )
        ).json()
        assert sub["parent_id"] == task["id"]

        # Listing returns the nested tree (subtasks populated)
        listing = await client.get(f"/api/v1/planner/tasks?list_id={lst['id']}")
        body = listing.json()
        assert any(t["id"] == task["id"] and len(t["subtasks"]) == 1 for t in body)

        # Nesting beyond 2 levels is rejected
        too_deep = await client.post(
            "/api/v1/planner/tasks",
            json={"title": "Too deep", "parent_id": sub["id"]},
        )
        assert too_deep.status_code == 400

        # Complete the subtask
        done = await client.patch(
            f"/api/v1/planner/tasks/{sub['id']}/complete", json={"completed": True}
        )
        assert done.status_code == 200
        assert done.json()["is_completed"] is True
        assert done.json()["completed_at"] is not None

        # Completed tasks hidden unless include_completed
        listing2 = await client.get(f"/api/v1/planner/tasks?list_id={lst['id']}")
        top = [t for t in listing2.json() if t["id"] == task["id"]][0]
        assert all(not s["is_completed"] for s in top["subtasks"])  # the done sub hidden

    async def test_reorder(self, client):
        a = (await client.post("/api/v1/planner/tasks", json={"title": "A"})).json()
        b = (await client.post("/api/v1/planner/tasks", json={"title": "B"})).json()
        resp = await client.post(
            "/api/v1/planner/tasks/reorder",
            json={"items": [
                {"id": a["id"], "new_sort_order": 2},
                {"id": b["id"], "new_sort_order": 1},
            ]},
        )
        assert resp.status_code == 200
        listing = await client.get("/api/v1/planner/tasks")
        order = [t["sort_order"] for t in listing.json()]
        assert order == sorted(order)


class TestPlannerSchedule:
    async def test_recurring_event_expands(self, client):
        # Monday 2026-07-13 at 09:00, weekly Mon/Wed/Fri for the week
        start = "2026-07-13T09:00:00"  # a Monday
        await client.post(
            "/api/v1/planner/events",
            json={
                "title": "Standup",
                "start_at": start,
                "end_at": "2026-07-13T09:15:00",
                "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
            },
        )
        resp = await client.get(
            "/api/v1/planner/agenda",
            params={"from": "2026-07-13T00:00:00", "to": "2026-07-17T23:59:59"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Mon (13), Wed (15), Fri (17) → 3 occurrences in that window
        assert body["total"] == 3
        assert all(item["is_recurring"] for item in body["items"])
        assert all(item["title"] == "Standup" for item in body["items"])

    async def test_one_off_event_appears_once(self, client):
        day = datetime(2026, 7, 14, 18, 0)
        await client.post(
            "/api/v1/planner/events",
            json={
                "title": "Dentist",
                "start_at": day.isoformat(),
                "end_at": (day + timedelta(hours=1)).isoformat(),
            },
        )
        resp = await client.get(
            "/api/v1/planner/agenda",
            params={"from": "2026-07-01T00:00:00", "to": "2026-07-31T23:59:59"},
        )
        items = [i for i in resp.json()["items"] if i["title"] == "Dentist"]
        assert len(items) == 1
        assert items[0]["is_recurring"] is False

    async def test_event_crud(self, client):
        ev = (
            await client.post(
                "/api/v1/planner/events",
                json={"title": "Lunch", "start_at": "2026-08-01T12:00:00", "end_at": "2026-08-01T13:00:00"},
            )
        ).json()
        upd = await client.patch(f"/api/v1/planner/events/{ev['id']}", json={"location": "Cafe"})
        assert upd.json()["location"] == "Cafe"
        dele = await client.delete(f"/api/v1/planner/events/{ev['id']}")
        assert dele.status_code == 204
        # Hidden from agenda
        resp = await client.get(
            "/api/v1/planner/agenda",
            params={"from": "2026-08-01T00:00:00", "to": "2026-08-01T23:59:59"},
        )
        assert not any(i["title"] == "Lunch" for i in resp.json()["items"])
