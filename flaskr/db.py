import os 
import sqlite3
from flask import Flask, g
from flask_sqlite_admin.core import sqliteAdminBlueprint
from werkzeug.security import generate_password_hash

app = Flask(__name__) # create the application instance :)
app.config.from_object(__name__) # load config from this file , flaskr.py

# Load default config and override config from an environment variable
app.config.update(dict(
    # DATABASE=os.path.join(app.root_path, 'flaskr.db'),
    SECRET_KEY='development key',
    USERNAME='admin',
    PASSWORD='default',
    FLASK_APP='flaskr',
    FLASK_DEBUG = 1
))
app.config.from_envvar('FLASKR_SETTINGS', silent=True)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']

# sqliteAdminBP = sqliteAdminBlueprint(dbPath = app.config['DATABASE'])
# app.register_blueprint(sqliteAdminBP, url_prefix='/sqlite') 

def connect_db():
    """Connects to the specific database."""
    rv = sqlite3.connect(app.config['DATABASE'])
    rv.row_factory = sqlite3.Row
    return rv

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = connect_db()
    return g.sqlite_db


def insert(table, fields=(), values=()):
    # g.db is the database connection
    cur = get_db().cursor()
    query = 'INSERT INTO %s (%s) VALUES (%s)' % (
        table,
        ', '.join(fields),
        ', '.join(['?'] * len(values))
    )
    cur.execute(query, values)
    get_db().commit()
    id = cur.lastrowid
    cur.close()
    return id

def delete(table, fields=(), values=()):
    # g.db is the database connection
    cur = get_db().cursor()
    query = 'DELETE FROM %s WHERE %s' % (
        table,
        (' = ? and '.join(fields)) + " = ?"
    )
    cur.execute('PRAGMA foreign_keys = ON')
    cur.execute(query, values)
    get_db().commit()
    print(cur.fetchall())
    id = cur.lastrowid
    cur.close()
    return id

@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()

def init_db():
    db = get_db()
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()

def seed_db():
    for x in range(1, 10):
        insert('users', ['username', 'password'], ['user' + str(x), generate_password_hash('user' + str(x))])
    
    print('seed_db completed')
    
@app.cli.command("initdb")
def initdb_command():
    """Initializes the database."""
    init_db()
    seed_db()
    print('Initialized the database.')
