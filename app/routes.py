from flask import Blueprint, render_template, redirect, url_for, request, flash, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from bson.objectid import ObjectId
from . import bcrypt, mongo
from .models import User
from .utils import save_file

main = Blueprint('main', __name__)

# ---------------- Register ----------------
@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')

        if mongo.db.users.find_one({'email': email}):
            flash('Email already exists!', 'danger')
            return redirect(url_for('main.index'))

        mongo.db.users.insert_one({'username': username, 'email': email, 'password': password, 'followers': [], 'following': []})
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('main.index'))
    return render_template('index.html')

# ---------------- Login ----------------
@main.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = mongo.db.users.find_one({'email': email})

        if user and bcrypt.check_password_hash(user['password'], password):
            user_obj = User(user)
            login_user(user_obj)
            session['username'] = user['username']
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid credentials!', 'danger')
    return render_template('index.html')

# ---------------- Logout ----------------
@main.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('main.index'))

# ---------------- Dashboard/Feed ----------------
@main.route('/dashboard')
@login_required
def dashboard():
    posts = list(mongo.db.posts.find().sort('created_at', -1))
    return render_template('dashboard.html', posts=posts, username=session['username'])

# ---------------- Upload Post ----------------
@main.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files['media']
        caption = request.form['caption']
        filename = save_file(file)
        if not filename:
            flash('Invalid file type', 'danger')
            return redirect(url_for('main.upload'))

        mongo.db.posts.insert_one({
            'user_id': current_user.id,
            'username': session['username'],
            'filename': filename,
            'caption': caption,
            'likes': [],
            'comments': [],
            'created_at': request.form.get('created_at', None)
        })
        flash('Post uploaded successfully!', 'success')
        return redirect(url_for('main.dashboard'))
    return render_template('upload.html')

@main.route('/search')
@login_required
def search():
    query = request.args.get('query')
    regex = {'$regex': query, '$options': 'i'}
    results = mongo.db.users.find({'username': regex})
    users = [User(user) for user in results if user['username'] != session['username']]
    posts = list(mongo.db.posts.find().sort('created_at', -1))
    return render_template('dashboard.html', posts=posts, username=session['username'], users=users)


# ---------------- Like Post ----------------
@main.route('/like/<post_id>')
@login_required
def like(post_id):
    user_id = current_user.id
    post = mongo.db.posts.find_one({'_id': ObjectId(post_id)})
    if post:
        if user_id not in post['likes']:
            mongo.db.posts.update_one({'_id': ObjectId(post_id)}, {'$addToSet': {'likes': user_id}})
        else:
            mongo.db.posts.update_one({'_id': ObjectId(post_id)}, {'$pull': {'likes': user_id}})
    return redirect(url_for('main.dashboard'))

# ---------------- Comment ----------------
@main.route('/comment/<post_id>', methods=['POST'])
@login_required
def comment(post_id):
    comment_text = request.form['comment']
    comment = {'user': session['username'], 'text': comment_text}
    mongo.db.posts.update_one({'_id': ObjectId(post_id)}, {'$push': {'comments': comment}})
    return redirect(url_for('main.dashboard'))

# ---------------- User Profile ----------------
@main.route('/profile/<username>')
@login_required
def profile(username):
    user = mongo.db.users.find_one({'username': username})
    if not user:
        flash('User not found!', 'danger')
        return redirect(url_for('main.dashboard'))

    posts = list(mongo.db.posts.find({'username': username}).sort('created_at', -1))
    is_following = current_user.id in user.get('followers', [])
    return render_template('profile.html', user=user, posts=posts, is_following=is_following)

@main.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    new_username = request.form['username'].strip()
    new_email = request.form['email'].strip()

    current_user_id = ObjectId(current_user.id)
    old_username = current_user.username

    # Check if new username/email already used by someone else
    existing_user = mongo.db.users.find_one({
        "$or": [{"username": new_username}, {"email": new_email}],
        "_id": {"$ne": current_user_id}
    })

    if existing_user:
        flash("Username or email already taken.", "danger")
        return redirect(url_for('main.profile', username=old_username))

    # Update user info
    mongo.db.users.update_one({"_id": current_user_id}, {
        "$set": {"username": new_username, "email": new_email}
    })

    # Update posts with new username
    mongo.db.posts.update_many({"user_id": current_user.id}, {
        "$set": {"username": new_username}
    })

    # Update comments with new username
    mongo.db.posts.update_many(
        {"comments.user": old_username},
        {"$set": {"comments.$[elem].user": new_username}},
        array_filters=[{"elem.user": old_username}]
    )

    # Update messages where user is sender
    mongo.db.messages.update_many({"sender": old_username}, {
        "$set": {"sender": new_username}
    })

    # Update messages where user is receiver
    mongo.db.messages.update_many({"receiver": old_username}, {
        "$set": {"receiver": new_username}
    })

    # Update session and current_user
    session['username'] = new_username
    current_user.username = new_username
    current_user.email = new_email

    flash("Profile updated successfully!", "success")
    return redirect(url_for('main.profile', username=new_username))

# ---------------- Follow / Unfollow ----------------
@main.route('/follow/<username>')
@login_required
def follow(username):
    target = mongo.db.users.find_one({'username': username})
    if not target:
        return redirect(url_for('main.dashboard'))

    mongo.db.users.update_one({'_id': ObjectId(target['_id'])}, {'$addToSet': {'followers': current_user.id}})
    mongo.db.users.update_one({'_id': ObjectId(current_user.id)}, {'$addToSet': {'following': str(target['_id'])}})
    return redirect(url_for('main.profile', username=username))

@main.route('/unfollow/<username>')
@login_required
def unfollow(username):
    target = mongo.db.users.find_one({'username': username})
    if not target:
        return redirect(url_for('main.dashboard'))

    mongo.db.users.update_one({'_id': ObjectId(target['_id'])}, {'$pull': {'followers': current_user.id}})
    mongo.db.users.update_one({'_id': ObjectId(current_user.id)}, {'$pull': {'following': str(target['_id'])}})
    return redirect(url_for('main.profile', username=username))

@main.route('/get_users')
@login_required
def get_users():
    user_ids = request.args.getlist('ids[]')
    users = list(mongo.db.users.find({'_id': {'$in': [ObjectId(uid) for uid in user_ids]}}))
    user_list = [{'username': user['username']} for user in users]
    return jsonify(user_list)

# ---------------- Chat Page ----------------
@main.route('/chat')
@login_required
def chat():
    user_data = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
    following_ids = user_data.get('following', [])
    following = [mongo.db.users.find_one({'_id': ObjectId(uid)}) for uid in following_ids]

    receiver = request.args.get('partner')
    messages = []
    if receiver:
        messages = list(mongo.db.messages.find({
            '$or': [
                {'sender': current_user.username, 'receiver': receiver},
                {'sender': receiver, 'receiver': current_user.username}
            ]
        }))

    return render_template('chat.html', username=current_user.username, following=following, messages=messages, receiver=receiver)

@main.route('/send_message', methods=['POST'])
@login_required
def send_message():
    receiver = request.form['receiver']
    message_text = request.form['message']

    mongo.db.messages.insert_one({
        'sender': current_user.username,
        'receiver': receiver,
        'text': message_text
    })

    return redirect(url_for('main.chat', partner=receiver))
