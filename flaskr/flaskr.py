import os
import sqlite3
from flask import Flask, request, session, g, redirect, url_for, abort, \
     render_template, flash, json
from flask_socketio import SocketIO, send, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, \
     check_password_hash
from flask_sqlite_admin.core import sqliteAdminBlueprint
import datetime
from db import *

socketio = SocketIO(app)


def getTime():
    return datetime.datetime.now()

@app.context_processor
def utility_processor():
    def format_date(d):
        t = datetime.datetime.strptime(d, "%Y-%m-%d %H:%M:%S.%f")
        t = str(t.strftime("%I:%M%p"))
        t = t.replace("AM", "am")
        t = t.replace("PM", "pm")
        return t
    return dict(format_date=format_date)

@app.route('/')
def home():
    print(session)
    if not session:
        # return render_template('layout.html')
        return login()
    else:
        return get_messages()

@app.route('/messages')
def get_messages():
    print(session)
    db = get_db()
    cur = db.execute('select * from conversations as c JOIN conversation_members as cm on c.id = cm.conversation_id ' + 
        'WHERE cm.member_id = ?;', [session['user_id']])
    entries = cur.fetchall()

    c_ids = []
    for entry in entries:
        c_ids.append(entry['id'])

    print("c_ids")
    print(c_ids)

    print(entries)

    members = {}
    latest_member_username = {}

    if len(c_ids) > 0:
        count = len(c_ids) - 1
        condition = ' or c.id = ? ' * count 
        cur = db.execute('select u.username as username, c.id as c_id, u.id as u_id, c.latest_member_id as c_latest_member_id from conversations as c JOIN conversation_members as cm on c.id = cm.conversation_id ' + 
            ' JOIN users as u on cm.member_id = u.id ' +
            'where c.id = ? ' + condition, c_ids)
        tempMembers = cur.fetchall()
        print("-------------------------")
        print("tempMembers")
        print(tempMembers)
        membersDict = {}
        for m in tempMembers:            
            # if m['c_id'] < len(membersDict):
            if m['username'] != session['username']:
                if m['c_id'] not in membersDict:
                    membersDict[m['c_id']] = []

                membersDict[m['c_id']].append(m['username'])    

            if m['u_id'] == m['c_latest_member_id']:
                latest_member_username[m['c_id']] = m['username']

        for m in membersDict:
            print(m)
            members[m] = ' & '.join(membersDict[m])
        # ' '.join(['word1', 'word2', 'word3'])

    if request.args.get('q') == 'deleted':
        flash("Conversation deleted")

    return render_template('get_messages.html', entries=entries, members=members or {}, latest_member_username=latest_member_username, user={'user_id': session['user_id'], 'username': session['username']})

def get_conversation_by_id(id):
    return query_db('select * from (select * from messages JOIN users ON messages.sender_id = users.id WHERE conversation_id = ? ORDER BY messages.id DESC limit 10) order by id asc;', [id])

@app.route('/conversation/<id>', methods=['GET'])
def get_conversation(id=None):
    db = get_db()
    conversation = query_db('select * from conversations WHERE id = ?', [id], one=True)

    c_members = query_db('select username from conversations as c JOIN conversation_members as cm ON c.id = cm.conversation_id JOIN users as u ON cm.member_id = u.id WHERE c.id = ?;', [id])

    messages = None
    if conversation:
        messages = get_conversation_by_id(id)

    members = []
    for m in c_members:
        if m['username'] != session['username']:
            members.append(m['username'])

    members = " & ".join(members)

    print("length is " + str(len(c_members)))
    return render_template('get_conversation.html', entry=conversation, messages=messages, members=members, last_member=c_members[len(c_members) - 1])

@app.route('/conversation/<id>/members', methods=['GET'])
def api_get_members(id=None):
    print("in api_get_members")
    c_members = query_db('select username from conversations as c JOIN conversation_members as cm ON c.id = cm.conversation_id JOIN users as u ON cm.member_id = u.id WHERE c.id = ?;', [id])
    members = []
    for m in c_members:
        if m['username'] != session['username']:
            members.append(m['username'])

    return json.jsonify(members)

@app.route('/api/conversation', methods=['POST'])
def api_get_conversation_by_members():

    print(request.form)
    members = request.form.getlist('members[]')
    members.append(session['username'])
    print("members")
    print(members)

    messages = get_c_messages_by_member_usernames(members)
    # messages = get_conversation_by_id(id)
    response = {}

    if messages:
        messages_list = []
        for m in messages:
            messages_list.append({"message": m['text'], "sender": m['username'], "time": utility_processor()['format_date'](str(m['created_at']))})
        response['messages'] = messages_list  
        response['conversation_id'] = messages[0]['conversation_id']

    return json.jsonify(response)

@app.route('/conversation/<id>', methods=['DELETE'])
def delete_conversation(id=None):
    print("delete request from client")
    delete_result = delete('conversations', ['id'], [id])
    print(delete_result)
    return json.jsonify({"result": "deleted", 'delete_result': delete_result})

@app.route('/add', methods=['POST'])
def add_entry():
    if not session.get('logged_in'):
        abort(401)
    db = get_db()
    db.execute('insert into entries (title, text) values (?, ?)',
        [request.form['title'], request.form['text']])
    db.commit()
    flash('New entry was successfully posted')
    data = {}
    data['title'] = request.form['title']
    data['text'] = request.form['text']
    socketio.emit('my event', data)
    return redirect(url_for('show_entries'))

def get_conversation_by_members(c_ids, member_ids):
    conversation = query_db('select c.id from conversations as c JOIN conversation_members as cm ON c.id = cm.conversation_id WHERE %s GROUP BY c.id HAVING COUNT(cm.member_id) = %s ' %
    ((' c.id = ? or ' * len(c_ids))[:-3], len(member_ids)), c_ids, one=True)        

    return conversation

def get_conversation_by_members_unknown_c_id(member_ids):
    conversation = query_db('select c.id from conversations as c JOIN conversation_members as cm ON c.id = cm.conversation_id GROUP BY c.id HAVING COUNT(cm.member_id) = ? ', [len(member_ids)], one=True)        

    return conversation

def get_c_id_by_member_usernames(member_usernames):
    print("in get_c_id_by_member_usernames")
    print(member_usernames)
    # Get conversations where they have at these member_usernames
    c_ids = query_db('select c.id from conversations as c JOIN conversation_members as cm ON c.id = cm.conversation_id JOIN users as u ON cm.member_id = u.id WHERE %s GROUP BY c.id HAVING COUNT(cm.member_id) = ?' %
            ((' username = ? or ' * len(member_usernames))[:-3]), member_usernames + [len(member_usernames)])

    c_ids_list = []
    for c_id in c_ids:
        c_ids_list.append(c_id['id'])

    print("c_ids_list")
    print(c_ids_list)

    if c_ids_list:
        # Get conversations where they have only member_usernames, no more.
        conversation = query_db('select c2.id from conversations as c2 JOIN conversation_members as cm2 ON c2.id = cm2.conversation_id WHERE %s GROUP BY c2.id HAVING COUNT(cm2.member_id) = ? ' % (" c2.id = ? or " * len(c_ids_list))[:-3], c_ids_list + [len(member_usernames)])        
        if conversation:
            c_id = conversation[0]['id']    
        else:
            c_id = None
    else:
        c_id = None

    return c_id

def get_c_id_by_member_ids(member_ids):
    print("in get_c_id_by_member_ids")
    print(member_ids)
    # Get conversations where they have at these member_usernames
    c_ids = query_db('select c.id from conversations as c JOIN conversation_members as cm ON c.id = cm.conversation_id WHERE %s GROUP BY c.id HAVING COUNT(cm.member_id) = ?' %
            ((' cm.member_id = ? or ' * len(member_ids))[:-3]), member_ids + [len(member_ids)])

    c_ids_list = []
    for c_id in c_ids:
        c_ids_list.append(c_id['id'])

    print("c_ids_list")
    print(c_ids_list)

    if c_ids_list:
        # Get conversations where they have only member_usernames, no more.
        conversation = query_db('select c2.id from conversations as c2 JOIN conversation_members as cm2 ON c2.id = cm2.conversation_id WHERE %s GROUP BY c2.id HAVING COUNT(cm2.member_id) = ? ' % (" c2.id = ? or " * len(c_ids_list))[:-3], c_ids_list + [len(member_ids)])        
        if conversation:
            c_id = conversation[0]['id']    
        else:
            c_id = None
    else:
        c_id = None

    return c_id

def get_c_messages_by_member_usernames(member_usernames):
    print("in get_c_messages_by_member_usernames")
    print(member_usernames)
    c_ids = query_db('select c.id from conversations as c JOIN conversation_members as cm ON c.id = cm.conversation_id JOIN users as u ON cm.member_id = u.id WHERE %s GROUP BY c.id HAVING COUNT(cm.member_id) = ?' %
            ((' username = ? or ' * len(member_usernames))[:-3]), member_usernames + [len(member_usernames)])

    c_ids_list = []
    for c_id in c_ids:
        c_ids_list.append(c_id['id'])

    if c_ids_list:
        messages = query_db('SELECT * FROM messages as m JOIN users as u ON m.sender_id = u.id WHERE conversation_id = (select c2.id from conversations as c2 JOIN conversation_members as cm2 ON c2.id = cm2.conversation_id WHERE %s GROUP BY c2.id HAVING COUNT(cm2.member_id) = ? )' % (" c2.id = ? or " * len(c_ids_list))[:-3], c_ids_list + [len(member_usernames)])        
    else:
        messages = []

    return messages

def update_conversation(latest_message, latest_member_id, udpated_at, c_id):
    db = get_db()
    db.execute('UPDATE conversations set latest_message = ?, latest_member_id = ?, updated_at = ? WHERE id = ?;', [latest_message, latest_member_id, udpated_at, c_id])    
    db.commit()

def usernamesToIds(usernames=None):
    print('usernames')
    print(usernames)
    if not usernames:
        return []

    us = query_db('SELECT id FROM users WHERE ' + ((' username = ? OR ' * len(usernames))[:-3]), usernames)
    return [u['id'] for u in us]

def idsToUsernames(ids=None):
    print('ids')
    print(ids)
    if not ids:
        return []

    us = query_db('SELECT username FROM users WHERE ' + ((' id = ? OR ' * len(ids))[:-3]), ids)
    return [u['username'] for u in us]

# messages to existing conversations.
@app.route('/api/message/new', methods=['POST'])
def new_message_api(): 
    print("-------------------------------------")
    print("request.form")
    print(request.form)
    print(request)

    time = getTime()

    update_conversation(request.form['msg'], session['user_id'], time, request.form['c_id'])

    msg_id = insert('messages', ['text', 'conversation_id', 'sender_id', 'created_at'], 
        [request.form['msg'], request.form['c_id'], session['user_id'], time])
    
    response = {}
    response['time'] = utility_processor()['format_date'](str(time))
    response['sender'] = session['username']
    response['msg_id'] = msg_id
    print('returning json response')
    socketio.emit("shit", room=request.form['c_id'], namespace='/')
    return json.jsonify(response)

#  to existing conversations.
@app.route('/api/conversation/<id>/members', methods=['POST'])
def api_update_conversation_members(id): 
    print("-------------------------------------")
    print("request.form")
    print(request.form)
    print(request.form.getlist('newMembers[]'))
    print(request.form.getlist('removedMembers[]'))

    members = request.form.getlist('newMembers[]')
    removedMembers = request.form.getlist('removedMembers[]')

    db = get_db()
    tempMembers = db.execute('SELECT member_id as id FROM conversation_members WHERE conversation_id = ? ', [id]).fetchall()    
    
    # The current user cannot be removed from the conversation, hence not included in updatedMembers.
    updatedMembers = [m['id'] for m in tempMembers if m['id'] is not session['user_id']]

    newMembers = usernamesToIds(members)
    removedMembers = usernamesToIds(removedMembers)

    for m in newMembers:
        if m not in updatedMembers:
            # add to updatedMembers
            updatedMembers.append(m)

    for m in removedMembers:
        if m in updatedMembers:
            updatedMembers.remove(m)

    # for cm in originalMembers:
    #     if cm['member_id'] not in members:
    #         members.append(cm['member_id'])

    # c_id = get_c_id_by_member_usernames(members)
    c_id = get_c_id_by_member_ids(updatedMembers)
    print("c_id")
    print(c_id)

    if c_id:
        response = {}

        response['url_redirect'] = url_for("get_conversation", id=c_id)
        # response['members'] = members

        # messages = get_conversation_by_id(c_id)
        # messages_list = []
        # for m in messages:
        #     messages_list.append({"message": m['text'], "sender": m['username'], "time": utility_processor()['format_date'](str(m['created_at']))})
        # response['messages'] = messages_list  

        return json.jsonify(response)
    else:
        if newMembers:
            cond = (" u_id = ? or " * len(newMembers))[:-3]    
            db.execute('INSERT INTO conversation_members (member_id, conversation_id) SELECT id as u_id, ? FROM users WHERE %s AND NOT EXISTS (SELECT * FROM conversation_members WHERE conversation_id = ? and member_id = u_id) ' % (cond), [id] + newMembers + [id])      
        if removedMembers:
            db.execute('DELETE FROM conversation_members WHERE (%s) AND conversation_id = ? ' % (" member_id = ? OR " * len(removedMembers))[:-3]  , removedMembers + [id])      
        
        db.commit()
        
        # usernames = db.execute('SELECT username FROM conversation_members as cm JOIN users as u ON cm.member_id = u.id WHERE cm.conversation_id = ?', [id]).fetchall()
        # member_ids = db.execute('SELECT u.id FROM conversation_members as cm JOIN users as u ON cm.member_id = u.id WHERE cm.conversation_id = ?', [id]).fetchall()
        
        # members = []
        # for um in usernames:
        #     if um['username'] != session['username']:
        #         members.append(um['username'])  

        # response = {'members': " & ".join(members)}

        # conversation = get_conversation_by_members_unknown_c_id(member_ids)

        # if conversation:
        #     # adding the supplied members results in a new conversation created, hence a url redirect is needed.
        #     if int(id) != int(conversation['id']):            
        #         print('id: '+ str(id))
        #         print('conversation["id"]: ' + str(conversation['id']))
        #         print(id != conversation['id'])
        #         response['url_redirect'] = url_for("get_conversation", id=conversation['id'])
        #         response['conversation_id'] = conversation['id']
        #     else:
        #         print('')

            # messages = get_conversation_by_id(conversation['id'])
            # messages_list = []
            # for m in messages:
            #     messages_list.append({"message": m['text'], "sender": m['username'], "time": utility_processor()['format_date'](str(m['created_at']))})
            # response['messages'] = messages_list  
        
        # response['time'] = utility_processor()['format_date'](str(time))
        # response['sender'] = session['username']
        # print('returning json response')
        # socketio.emit("shit", room=request.form['c_id'], namespace='/')
        print("id is " + str(id))
        print(id == 3)
        print(type(id))
        usernames = idsToUsernames(updatedMembers)
        usernames.append(session['username'])
        socketio.emit('updatedMembers', {'updatedMembers': usernames}, namespace='/', room=int(id))
        response = {"status": 'success', "updatedMembers": usernames}

        return json.jsonify(response)

@app.route('/api/message/<id>', methods=['POST'])
def api_edit_message(id): 
    print(request.form)
    db = get_db()
    message = query_db('select * from messages WHERE id = ?', [id], one=True)
    old_text = message['text']

    # if not message['updated_at']:
    #     db.execute('INSERT INTO messages_revisions (message_id, revision_version, sender_id, created_at, text) VALUES (?, 1, ?, ?);', [id, session['user_id'], message['created_at'], old_text])    
    # else:
    db.execute('INSERT INTO messages_revisions (message_id, revision_version, sender_id, created_at, text) VALUES (?, (SELECT IFNULL(MAX(revision_version), 0) + 1 FROM messages_revisions WHERE message_id = ?), ?, ?, ?);', [id, id, session['user_id'], message['updated_at'], old_text])    
    
    db.execute('UPDATE messages set text = ?, updated_at = ? WHERE id = ?;', [request.form['text'], getTime(), id])    
    db.commit()

    response = {'status': 'success'}
    return json.jsonify(response)

@app.route('/api/message/<id>', methods=['DELETE'])
def api_delete_message(id=None):
    print(request.form)
    delete_result = delete('messages', ['id'], [id])
    print(delete_result)
    return json.jsonify({"result": "deleted", 'delete_result': delete_result})

@app.route('/message/new', methods=['GET', 'POST'])
def new_message(): 
    if not session.get('logged_in'):
        abort(401)
    error = None
    if request.method == 'POST':

        message = request.form['text']
        sender_id = session['user_id']        
        sender_username = session['username']
        members = request.form.getlist('user')
        members.append(sender_username)
        time = getTime()

        conversation_id = get_c_id_by_member_usernames(members)

        # conversation with the supplied members does not yet exist.
        if not conversation_id:
            # insert conversation
            conversation_id = insert('conversations', ['sender_id', 'latest_message', 'latest_member_id', 'created_at', 'updated_at'], 
                        [sender_id, message, sender_id, time, time])

            member_ids = query_db('select id from users WHERE %s ' %
                (' username = ? OR ' * (len(members)))[:-3], members)
            member_ids_list = []
            for m in member_ids:
                member_ids_list.append(m['id'])

            db = get_db()
            # insert members
            for m_id in member_ids_list:
                db.execute('insert into conversation_members (conversation_id, member_id) select ?, ? ' + 
                    'WHERE NOT EXISTS(SELECT * FROM conversation_members WHERE conversation_id = ? and member_id = ?);', 
                    [conversation_id, m_id, conversation_id, m_id])
            db.commit()
        else:
            update_conversation(message, sender_id, time, conversation_id)

        # insert message
        insert('messages', ['text', 'conversation_id', 'sender_id', 'created_at', 'updated_at'], 
            [message, conversation_id, sender_id, time, time])


        socketio.emit('new_message', {'message': message, 'time': utility_processor()['format_date'](str(time)), 'sender': sender_username }, room=conversation_id)

        return redirect(url_for("get_conversation", id=conversation_id))

    return render_template('new_message.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        if not request.form['username']:
            error = 'Invalid username'
        elif not request.form['password']:
            error = 'Invalid password'
        else:
            if session.get('logged_in'):
                abort(401)
            hashed_password = generate_password_hash(request.form['password'])
            # print(request.form['password'])
            # print str(h)
            user_id = insert('users', ['username', 'password'], 
            [request.form['username'], hashed_password])
            # data = {}
            session['logged_in'] = True
            session['username'] = request.form['username']
            session['user_id'] = user_id
            flash('You were registered')
            return redirect(url_for('new_message'))
    return render_template('register.html', error=error)

@app.route('/newpassword', methods=['GET', 'POST'])
def newpassword():
    error = None
    if request.method == 'POST':
        error = 'just a placeholder'
    return render_template('newpassword.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if not request.form['username']:
            error = 'empty username'
        # elif request.form['password'] != app.config['PASSWORD']:
        elif not request.form['password']:
            error = 'empty password'
        else:
            user = query_db('select * from users where username = ?',
                [request.form['username']], one=True)
            
            if user is not None and check_password_hash(user['password'], request.form['password']):                        
                session['logged_in'] = True
                session['user_id'] = user['id'];
                session['username'] = user['username'];
                flash('You were logged in')
                return redirect(url_for('get_messages'))
            # if user is None or not check_password_hash(user['password'], request.form['password']):
            #     error = 'wrong username and password combo'
            else:
                # print the_username, 'has the id', user['user_id']
                error = 'wrong username and password combo'

    if session:
        return redirect(url_for('get_messages'))

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You were logged out')
    session.clear()
    return redirect(url_for('home'))


@app.route('/username')
def username():
    username = request.args.get('q')
    print('username search')
    print(request.form)
    print(request.args)
    print(username)
    users = query_db('select * from users where username LIKE ?',
                ["%" + username + "%"])    
    response = []
    for user in users:
        if user['username'] != session['username']:
            response.append(user['username'])

    print("usernames to return")
    print(response)
    return json.jsonify(response)


@socketio.on('connect')
def handle_my_custom_event():
    print("------------------------------------")
    print("connect handler")
    print(session['username'])
    o = {}
    o['id'] = 1
    emit('user_info', {'id': session['user_id'], 'username': session['username']}, broadcast=False)
    # o['username'] = "shit"
    # emit('user_info', json.jsonify(o), room=json['room'], namespace='/')
    # socketio.emit('my event', "received by client")

@socketio.on('new_message')
def handle_new_messgae(json):
    print('received json: ' + str(json))
    emit('new_message', json, room=json['room'], namespace='/')

@socketio.on('edited_message')
def handle_edited_messgae(json):
    print('received json: ' + str(json))
    emit('edited_message', json, room=json['room'], namespace='/')

@socketio.on('connect_to_convo')
def handle_my_custom_event(json):
    socketio.join(json.c_id)
    print("------------------------------------")
    print('request to join convo')
    print(str(json))
    # socketio.emit('my event', "received by client")

@socketio.on('join')
def on_join(data):
    print("------------------------------------")
    print('request to join convo: join')
    username = session['username']
    room = data['room']
    join_room(room, namespace='/')
    send(username + ' has entered room ' + str(room), room=room, namespace='/')

@socketio.on('leave')
def on_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    send(username + ' has left the room.', room=room, namespace='/')


if __name__ == '__main__':
    # socketio.run(app)
    
    app.run(debug=True, use_reloader=True)