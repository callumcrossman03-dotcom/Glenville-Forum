from app.models import Community, CommunityModerator, PollOption, PollVote, Post, User, Vote, db
from tests.conftest import login


def first_community_id(slug="campus-life"):
    return Community.query.filter_by(slug=slug).first().id


def test_register_redirects_to_onboarding(client):
    response = client.post(
        "/auth/register",
        data={"username": "newuser", "email": "new@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/onboarding" in response.headers["Location"]


def test_create_post_and_vote(client, app):
    login(client)
    with app.app_context():
        community_id = first_community_id()
    response = client.post(
        "/posts/new",
        data={"title": "Test post", "body": "Hello campus", "post_type": "discussion", "community_id": community_id},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        post = Post.query.filter_by(title="Test post").first()
        assert post is not None
        vote_response = client.post(f"/posts/{post.id}/vote", data={"value": "1"}, headers={"X-Requested-With": "fetch"})
        assert vote_response.status_code == 200
        assert vote_response.get_json()["score"] == 1
        assert Vote.query.filter_by(post_id=post.id).count() == 1


def test_poll_creation_and_response(client, app):
    login(client)
    with app.app_context():
        community_id = first_community_id()
    client.post(
        "/posts/new",
        data={
            "title": "Lunch poll",
            "body": "Pick lunch",
            "post_type": "poll",
            "community_id": community_id,
            "poll_options": "Pizza\nTacos\nSalad",
        },
    )
    with app.app_context():
        post = Post.query.filter_by(title="Lunch poll").first()
        assert len(post.poll_options) == 3
        option = post.poll_options[0]
        response = client.post(f"/posts/{post.id}/poll", data={"option_id": option.id}, headers={"X-Requested-With": "fetch"})
        assert response.status_code == 200
        assert response.get_json()["total"] == 1
        assert PollVote.query.filter_by(post_id=post.id).count() == 1


def test_community_moderator_can_pin_only_assigned_community(client, app):
    with app.app_context():
        mod = User.query.filter_by(username="mod").first()
        campus = Community.query.filter_by(slug="campus-life").first()
        events = Community.query.filter_by(slug="events").first()
        author = User.query.filter_by(username="student").first()
        campus_post = Post(title="Campus mod post", body="Body", post_type="discussion", author=author, community=campus)
        events_post = Post(title="Events post", body="Body", post_type="discussion", author=author, community=events)
        db.session.add_all([campus_post, events_post, CommunityModerator(user=mod, community=campus, role="moderator")])
        db.session.commit()
        campus_id = campus_post.id
        events_id = events_post.id

    login(client, "mod")
    ok = client.post(f"/admin/posts/{campus_id}/pin", follow_redirects=False)
    forbidden = client.post(f"/admin/posts/{events_id}/pin", follow_redirects=False)
    assert ok.status_code == 302
    assert forbidden.status_code == 403
    with app.app_context():
        assert db.session.get(Post, campus_id).is_pinned is True
        assert db.session.get(Post, events_id).is_pinned is False


def test_admin_can_assign_and_remove_community_moderator(client, app):
    login(client, "admin")
    with app.app_context():
        community_id = first_community_id()
    response = client.post(
        "/admin/community-moderators",
        data={"username": "student", "community_id": community_id, "role": "moderator", "action": "add"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(username="student").first()
        assert CommunityModerator.query.filter_by(user_id=user.id, community_id=community_id).first() is not None

    client.post(
        "/admin/community-moderators",
        data={"username": "student", "community_id": community_id, "role": "moderator", "action": "remove"},
        follow_redirects=False,
    )
    with app.app_context():
        user = User.query.filter_by(username="student").first()
        assert CommunityModerator.query.filter_by(user_id=user.id, community_id=community_id).first() is None
