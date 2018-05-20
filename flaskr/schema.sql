create table if not exists users (
	id integer primary key autoincrement,
	username text not null,
	password text
);

create index if not exists username_index on users (username);

create table if not exists messages (
	id integer primary key autoincrement,
	'text' text not null,
	sender_id integer,
	conversation_id integer, 
	created_at datetime,
	updated_at datetime,
	FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE, 
    FOREIGN KEY (sender_id) REFERENCES users(id)
);

create table if not exists messages_revisions (
	id integer primary key autoincrement,
	message_id integer,
	revision_version integer not null,
	sender_id integer,
	created_at datetime,
	'text' text not null,
	FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
	FOREIGN KEY(sender_id) REFERENCES users(id)
);

create table if not exists conversations (
	id integer primary key autoincrement,
	sender_id integer,
	latest_message text,
	latest_member_id integer,
	created_at datetime,
	updated_at datetime,
	FOREIGN KEY (sender_id) REFERENCES users(id),
	FOREIGN KEY (latest_member_id) REFERENCES users(id)
);

create table if not exists conversation_members (
	id integer primary key autoincrement,
	member_id integer,
	conversation_id integer,
	FOREIGN KEY (member_id) REFERENCES users(id),
	FOREIGN KEY (conversation_id) REFERENCES conversations(id)
	ON DELETE CASCADE
);
	