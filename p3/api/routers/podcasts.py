"""Podcast CRUD routes."""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from p3.api.deps import get_db, load_config
from p3.api.models import PodcastCreate, PodcastOut, FetchAction
from p3.api.tasks import task_fetch

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


@router.get("", response_model=list[PodcastOut])
def list_podcasts():
    db = get_db()
    podcasts = db.get_all_podcasts()
    # Attach episode count
    for p in podcasts:
        eps = db.get_episodes_by_podcast(p["id"])
        p["episode_count"] = len(eps)
    return podcasts


@router.get("/{podcast_id}", response_model=PodcastOut)
def get_podcast(podcast_id: int):
    db = get_db()
    podcast = db.get_podcast_by_id(podcast_id)
    if not podcast:
        raise HTTPException(404, "Podcast not found")
    eps = db.get_episodes_by_podcast(podcast_id)
    podcast["episode_count"] = len(eps)
    return podcast


@router.post("", response_model=dict)
def add_podcast(body: PodcastCreate, background_tasks: BackgroundTasks):
    """Add a podcast by RSS URL and start fetching episodes."""
    db = get_db()

    # Check if already exists
    existing = db.get_podcast_by_url(body.url)
    if existing:
        raise HTTPException(409, "Podcast with this URL already exists")

    # Use provided name or derive from URL
    name = body.name or body.url.split("/")[-1] or "Untitled Podcast"
    podcast_id = db.add_podcast(name, body.url, body.category)

    # Kick off fetch in background
    job_id = db.create_job("fetch", episode_id=None)
    background_tasks.add_task(task_fetch, job_id, podcast_id, None)

    return {"podcast_id": podcast_id, "job_id": job_id}


@router.post("/{podcast_id}/fetch", response_model=dict)
def fetch_podcast(podcast_id: int, body: FetchAction = None, background_tasks: BackgroundTasks = None):
    """Trigger a new fetch for an existing podcast."""
    db = get_db()
    podcast = db.get_podcast_by_id(podcast_id)
    if not podcast:
        raise HTTPException(404, "Podcast not found")

    max_eps = body.max_episodes if body else None
    job_id = db.create_job("fetch", episode_id=None)
    background_tasks.add_task(task_fetch, job_id, podcast_id, max_eps)
    return {"job_id": job_id}


@router.delete("/{podcast_id}")
def delete_podcast(podcast_id: int):
    db = get_db()
    podcast = db.get_podcast_by_id(podcast_id)
    if not podcast:
        raise HTTPException(404, "Podcast not found")
    db.delete_podcast(podcast_id)
    return {"deleted": True}
