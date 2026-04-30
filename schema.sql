CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(40) NOT NULL UNIQUE,
    display_name VARCHAR(80),
    bio VARCHAR(280),
    avatar_color VARCHAR(20) NOT NULL DEFAULT '#005bab',
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_users_username ON users (username);
CREATE INDEX ix_users_email ON users (email);

CREATE TABLE communities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(40) NOT NULL UNIQUE,
    slug VARCHAR(40) NOT NULL UNIQUE,
    description VARCHAR(255) NOT NULL,
    icon VARCHAR(8) NOT NULL DEFAULT 'GS',
    created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_communities_name ON communities (name);
CREATE INDEX ix_communities_slug ON communities (slug);

INSERT INTO communities (name, slug, description, icon) VALUES
    ('Campus Life', 'campus-life', 'Dorms, dining, events, and everyday life at Glenville State.', 'GS'),
    ('Classes', 'classes', 'Talk about courses, professors, registration, and study tips.', 'CL'),
    ('Questions', 'questions', 'Ask for help, advice, and second opinions.', '?'),
    ('Athletics', 'athletics', 'Pioneers sports, intramurals, training, and game day threads.', 'AT'),
    ('Clubs', 'clubs', 'Student organizations, meetups, volunteer work, and club announcements.', 'CB'),
    ('Buy Sell Trade', 'buy-sell-trade', 'Textbooks, furniture, rides, tickets, and student deals.', '$'),
    ('Housing', 'housing', 'Roommates, residence halls, apartments, and housing questions.', 'HM'),
    ('Events', 'events', 'Campus events, local plans, deadlines, and things to do nearby.', 'EV'),
    ('Food', 'food', 'Dining hall thoughts, local restaurants, coffee, and late-night food.', 'FD'),
    ('Showcase', 'showcase', 'Share projects, wins, experiments, and discoveries.', 'SH');

CREATE TABLE posts (
    id SERIAL PRIMARY KEY,
    title VARCHAR(180) NOT NULL,
    body TEXT NOT NULL,
    post_type VARCHAR(20) NOT NULL DEFAULT 'discussion',
    image_filename VARCHAR(255),
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    community_id INTEGER NOT NULL REFERENCES communities(id) ON DELETE CASCADE
);

CREATE INDEX ix_posts_user_id ON posts (user_id);
CREATE INDEX ix_posts_community_id ON posts (community_id);
CREATE INDEX ix_posts_created_at ON posts (created_at DESC);

CREATE TABLE comments (
    id SERIAL PRIMARY KEY,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE
);

CREATE INDEX ix_comments_user_id ON comments (user_id);
CREATE INDEX ix_comments_post_id ON comments (post_id);
CREATE INDEX ix_comments_parent_id ON comments (parent_id);
CREATE INDEX ix_comments_created_at ON comments (created_at ASC);

CREATE TABLE votes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    value INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_post_vote UNIQUE (user_id, post_id),
    CONSTRAINT uq_user_comment_vote UNIQUE (user_id, comment_id),
    CONSTRAINT ck_vote_targets_one_item CHECK (
        (post_id IS NOT NULL AND comment_id IS NULL)
        OR
        (post_id IS NULL AND comment_id IS NOT NULL)
    ),
    CONSTRAINT ck_vote_value CHECK (value IN (-1, 1))
);

CREATE INDEX ix_votes_user_id ON votes (user_id);
CREATE INDEX ix_votes_post_id ON votes (post_id);
CREATE INDEX ix_votes_comment_id ON votes (comment_id);

CREATE TABLE saved_posts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_saved_post UNIQUE (user_id, post_id)
);

CREATE INDEX ix_saved_posts_user_id ON saved_posts (user_id);
CREATE INDEX ix_saved_posts_post_id ON saved_posts (post_id);

CREATE TABLE community_memberships (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    community_id INTEGER NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_community_membership UNIQUE (user_id, community_id)
);

CREATE INDEX ix_community_memberships_user_id ON community_memberships (user_id);
CREATE INDEX ix_community_memberships_community_id ON community_memberships (community_id);

CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    message VARCHAR(255) NOT NULL,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);
CREATE INDEX ix_notifications_actor_id ON notifications (actor_id);
CREATE INDEX ix_notifications_post_id ON notifications (post_id);
CREATE INDEX ix_notifications_comment_id ON notifications (comment_id);

CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    location VARCHAR(120) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    community_id INTEGER REFERENCES communities(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_events_starts_at ON events (starts_at);
CREATE INDEX ix_events_user_id ON events (user_id);
CREATE INDEX ix_events_community_id ON events (community_id);

CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_messages_sender_id ON messages (sender_id);
CREATE INDEX ix_messages_recipient_id ON messages (recipient_id);

CREATE TABLE reports (
    id SERIAL PRIMARY KEY,
    reporter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    reason VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    CONSTRAINT ck_report_targets_one_item CHECK (
        (post_id IS NOT NULL AND comment_id IS NULL)
        OR
        (post_id IS NULL AND comment_id IS NOT NULL)
    )
);

CREATE INDEX ix_reports_reporter_id ON reports (reporter_id);
CREATE INDEX ix_reports_post_id ON reports (post_id);
CREATE INDEX ix_reports_comment_id ON reports (comment_id);
CREATE INDEX ix_reports_status ON reports (status);
