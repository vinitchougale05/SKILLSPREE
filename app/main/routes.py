import os
import io
import datetime
import math
import secrets
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file, current_app
from functools import wraps
from bson import ObjectId
import bcrypt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color

from . import main
from app import mongo
from app.ml_utils import generate_quiz_questions, get_course_recommendations
from app.youtube_utils import canonical_youtube_url

# Sample data for development/testing
SAMPLE_GOALS = [
    'Java Developer', 'Python Developer', 'Web Developer', 
    'Data Scientist', 'Mobile App Developer', 'DevOps Engineer'
]

SAMPLE_QUIZ_QUESTIONS = {
    'Java Developer': [
        {
            'question': 'What is the main method signature in Java?',
            'options': ['public static void main(String[] args)', 'public void main(String[] args)',
                        'static void main(String[] args)', 'public main(String[] args)'],
            'correct': 0, 'difficulty': 'easy'
        },
        {
            'question': 'Which keyword is used for inheritance in Java?',
            'options': ['implements', 'extends', 'inherits', 'super'],
            'correct': 1, 'difficulty': 'easy'
        },
        {
            'question': 'What is encapsulation in Java?',
            'options': ['Hiding implementation details', 'Creating objects', 'Method overloading', 'Exception handling'],
            'correct': 0, 'difficulty': 'medium'
        }
    ],
    'Python Developer': [
        {
            'question': 'Which of the following is used to define a function in Python?',
            'options': ['function', 'def', 'func', 'define'],
            'correct': 1, 'difficulty': 'easy'
        },
        {
            'question': 'What is the correct way to create a list in Python?',
            'options': ['list = []', 'list = ()', 'list = {}', 'list = <>'],
            'correct': 0, 'difficulty': 'easy'
        },
        {
            'question': 'Which method is used to add an element to a list?',
            'options': ['add()', 'append()', 'insert()', 'push()'],
            'correct': 1, 'difficulty': 'medium'
        }
    ],
    'Web Developer': [
        {
            'question': 'What does HTML stand for?',
            'options': ['Hyper Text Markup Language', 'Home Tool Markup Language', 'Hyperlinks and Text Markup Language', 'Hyper Text Making Language'],
            'correct': 0, 'difficulty': 'easy'
        },
        {
            'question': 'Which CSS property is used to change the text color?',
            'options': ['font-color', 'text-color', 'color', 'foreground-color'],
            'correct': 2, 'difficulty': 'medium'
        },
        {
            'question': 'What is the correct HTML element for the largest heading?',
            'options': ['<h6>', '<h1>', '<heading>', '<header>'],
            'correct': 1, 'difficulty': 'easy'
        }
    ]
}

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login'))
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        if not user or not user.get('is_admin', False):
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def generate_unique_certificate_id():
    while True:
        certificate_code = secrets.token_hex(8).upper()
        existing = mongo.db.users.find_one({'certificates.certificate_id': certificate_code})
        if not existing:
            return certificate_code

def add_to_bookmarks(user_id, course_url):
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$addToSet': {'bookmarked_courses': course_url}}
    )

def save_test_results_to_file(user, quiz_result):
    try:
        results_dir = os.path.join(os.getcwd(), 'Test Results')
        if not os.path.exists(results_dir):
            os.makedirs(results_dir)
        
        test_date = quiz_result['date']
        filename = test_date.strftime('%Y-%m-%d_%H-%M-%S') + '_assessment.txt'
        filepath = os.path.join(results_dir, filename)
        
        content = []
        content.append("=" * 80)
        content.append("SKILL ASSESSMENT RESULTS")
        content.append("=" * 80)
        content.append(f"\nStudent Name: {user.get('name', 'Unknown')}")
        content.append(f"Email: {user.get('email', 'Unknown')}")
        content.append(f"Learning Goal: {quiz_result.get('learning_goal', 'Not specified')}")
        content.append(f"Test Date: {test_date.strftime('%B %d, %Y at %I:%M %p')}")
        content.append(f"\nScore: {quiz_result['score']}/{quiz_result['total']}")
        content.append(f"Percentage: {quiz_result['percentage']:.1f}%")
        content.append(f"Skill Level: {quiz_result['level']}")
        content.append("\n" + "=" * 80)
        content.append("DETAILED ANSWERS")
        content.append("=" * 80 + "\n")
        
        for i, result in enumerate(quiz_result.get('detailed_results', []), 1):
            content.append(f"Question {i}: [{result.get('difficulty', 'N/A').upper()}]")
            content.append(f"{result['question']}\n")
            
            for j, option in enumerate(result['options']):
                marker = ""
                if j == result['user_answer'] and j == result['correct_answer']:
                    marker = " ✓ [YOUR ANSWER - CORRECT]"
                elif j == result['user_answer']:
                    marker = " ✗ [YOUR ANSWER - INCORRECT]"
                elif j == result['correct_answer']:
                    marker = " ✓ [CORRECT ANSWER]"
                
                content.append(f"  {chr(65+j)}. {option}{marker}")
            
            content.append("")
        
        content.append("=" * 80)
        content.append(f"End of Assessment Results - Generated on {test_date.strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("=" * 80)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content))
        
        print(f"Debug - Test results saved to: {filepath}")
        
    except Exception as e:
        print(f"Error saving test results to file: {e}")

def get_latest_assessment_from_file(user_email):
    results_dir = os.path.join(os.getcwd(), 'Test Results')
    if not os.path.exists(results_dir):
        return None
    
    search_dirs = [results_dir]
    old_dir = os.path.join(results_dir, 'old')
    if os.path.exists(old_dir):
        search_dirs.append(old_dir)
        
    all_files = []
    for d in search_dirs:
        try:
            files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith('_assessment.txt')]
            all_files.extend(files)
        except Exception:
            pass
            
    if not all_files:
        return None
        
    all_files.sort(key=lambda x: os.path.basename(x), reverse=True)
    
    for filepath in all_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                clean_email = user_email.strip()
                if clean_email and f"Email: {clean_email}".lower() in content.lower():
                    return parse_assessment_file(content)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue
            
    return None

def parse_assessment_file(content):
    lines = content.split('\n')
    result = {}
    
    for line in lines:
        line = line.strip()
        if line.startswith("Learning Goal:"):
            result['learning_goal'] = line.replace("Learning Goal:", "").strip()
        elif line.startswith("Score:"):
            parts = line.replace("Score:", "").strip().split('/')
            if len(parts) == 2:
                result['score'] = int(parts[0])
                result['total'] = int(parts[1])
        elif line.startswith("Percentage:"):
            result['percentage'] = float(line.replace("Percentage:", "").replace("%", "").strip())
        elif line.startswith("Skill Level:"):
            result['level'] = line.replace("Skill Level:", "").strip()
            
    return result

@main.app_errorhandler(500)
def internal_error(error):
    import traceback
    return f"<h1>500 Internal Server Error</h1><pre>{traceback.format_exc()}</pre><br>Original error: {error}", 500

@main.route('/')
def index():
    return render_template('index.html')

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        if mongo.db.users.find_one({'email': email}):
            flash('Email already registered!', 'error')
            return redirect(url_for('main.register'))

        hashed_password = hash_password(password)
        user_data = {
            'name': name,
            'email': email,
            'password': hashed_password,
            'is_admin': False,
            'created_at': datetime.datetime.now(),
            'learning_goal': None,
            'skill_level': 0,
            'courses': [],
            'certificates': [],
            'quiz_history': []
        }

        result = mongo.db.users.insert_one(user_data)
        session['user_id'] = str(result.inserted_id)
        flash('Registration successful!', 'success')
        return redirect(url_for('main.onboarding'))

    return render_template('register.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = mongo.db.users.find_one({'email': email})

        if user and check_password(password, user['password']):
            session['user_id'] = str(user['_id'])
            session['is_admin'] = bool(user.get('is_admin', False))
            flash('Login successful!', 'success')

            if user.get('is_admin', False):
                return redirect(url_for('main.admin_dashboard'))

            if not user.get('learning_goal'):
                return redirect(url_for('main.onboarding'))

            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid email or password!', 'error')

    return render_template('login.html')

@main.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

@main.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    if request.method == 'POST':
        learning_goal = request.form['learning_goal']

        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$set': {'learning_goal': learning_goal}}
        )

        flash(f'Learning goal set: {learning_goal}', 'success')
        return redirect(url_for('main.assessment'))

    return render_template('onboarding.html', goals=SAMPLE_GOALS)

@main.route('/assessment', methods=['GET', 'POST'])
@login_required
def assessment():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    learning_goal = user.get('learning_goal')

    if not learning_goal:
        return redirect(url_for('main.onboarding'))

    if request.method == 'POST':
        questions = session.get('current_quiz_questions', [])
        
        if not questions:
            flash('Quiz session expired. Please try again.', 'error')
            return redirect(url_for('main.assessment'))
        
        answers = []
        score = 0
        detailed_results = []

        for i, question in enumerate(questions):
            user_answer = int(request.form.get(f'question_{i}', -1))
            correct_answer = question['correct']
            is_correct = user_answer == correct_answer
            
            answers.append(user_answer)
            if is_correct:
                score += 1
            
            detailed_results.append({
                'question': question['question'],
                'options': question['options'],
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'is_correct': is_correct,
                'difficulty': question.get('difficulty', 'medium')
            })

        percentage = (score / len(questions)) * 100 if questions else 0

        if percentage >= 80:
            level = 'Advanced'
        elif percentage >= 60:
            level = 'Intermediate'
        else:
            level = 'Beginner'

        quiz_result = {
            'date': datetime.datetime.now(),
            'score': score,
            'total': len(questions),
            'percentage': percentage,
            'level': level,
            'learning_goal': learning_goal,
            'detailed_results': detailed_results
        }

        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {
                '$set': {'skill_level': percentage},
                '$push': {'quiz_history': quiz_result}
            }
        )

        save_test_results_to_file(user, quiz_result)

        session.pop('current_quiz_questions', None)
        session['quiz_result'] = quiz_result
        return redirect(url_for('main.assessment_results'))

    print(f"Debug - Generating quiz questions for {learning_goal}")
    questions = generate_quiz_questions(learning_goal, num_questions=10)
    
    if not questions:
        print("Debug - Falling back to hardcoded questions")
        questions = SAMPLE_QUIZ_QUESTIONS.get(learning_goal, [])
        if not questions:
            flash('No questions available for this learning goal. Please select a different goal.', 'error')
            return redirect(url_for('main.onboarding'))
    
    session['current_quiz_questions'] = questions
    return render_template('assessment.html', questions=questions, learning_goal=learning_goal)

@main.route('/regenerate-recommendations')
@login_required
def regenerate_recommendations():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    quiz_history = user.get('quiz_history', [])
    
    last_result = None
    if quiz_history:
        last_result = quiz_history[-1]
    else:
        last_result = get_latest_assessment_from_file(user.get('email'))
        
    if not last_result:
        flash('No previous assessment found. Please take the assessment first.', 'warning')
        return redirect(url_for('main.assessment'))
    
    session['quiz_result'] = last_result
    session['is_regeneration'] = True
    session.pop('recommended_courses', None)
    
    flash('Generating fresh recommendations based on your previous assessment...', 'info')
    return redirect(url_for('main.assessment_results'))

@main.route('/assessment-results')
@login_required
def assessment_results():
    quiz_result = session.pop('quiz_result', None)
    if not quiz_result:
        return redirect(url_for('main.dashboard'))

    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    learning_goal = user.get('learning_goal')
    skill_level = user.get('skill_level', 0)
    is_regeneration = session.pop('is_regeneration', False)

    recommended_courses = get_course_recommendations(
        learning_goal=learning_goal,
        skill_level=skill_level,
        quiz_results=quiz_result,
        is_regeneration=is_regeneration
    )
    
    session['recommended_courses'] = recommended_courses
    bookmarked_urls = [b.get('url') for b in user.get('bookmarked_courses', [])]

    return render_template('assessment_results.html',
                           quiz_result=quiz_result,
                           recommended_courses=recommended_courses,
                           learning_goal=learning_goal,
                           bookmarked_urls=bookmarked_urls)

@main.route('/dashboard')
@login_required
def dashboard():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

    all_courses = user.get('courses', [])
    total_courses = len(all_courses)
    completed_courses = len([c for c in all_courses if c.get('completed', False)])
    certificates_earned = len(user.get('certificates', []))

    quiz_history = user.get('quiz_history') or []
    has_assessment_history = bool(quiz_history)

    user_email = user.get('email', '').strip()
    if user_email:
        latest_file_result = get_latest_assessment_from_file(user_email)
        if latest_file_result:
            has_assessment_history = True

    ongoing_courses = []
    for i, course in enumerate(all_courses):
        if not course.get('completed', False):
            course_with_index = course.copy()
            course_with_index['original_index'] = i
            ongoing_courses.append(course_with_index)
    
    recommended_courses = session.get('recommended_courses', [])
    enrolled_course_titles = {course.get('title') for course in all_courses}
    available_recommended_courses = [
        course for course in recommended_courses 
        if course.get('title') not in enrolled_course_titles
    ]
    
    recommendations_count = len(available_recommended_courses)
    bookmarked_urls = [b.get('url') for b in user.get('bookmarked_courses', [])]

    return render_template('dashboard.html',
                           user=user,
                           total_courses=total_courses,
                           completed_courses=completed_courses,
                           certificates_earned=certificates_earned,
                           quiz_history=quiz_history,
                           has_assessment_history=has_assessment_history,
                           courses=ongoing_courses,
                           recommended_courses=available_recommended_courses,
                           recommendations_count=recommendations_count,
                           bookmarked_urls=bookmarked_urls)

@main.route('/my-courses')
@login_required
def my_courses():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

    courses = user.get('courses', [])
    total_courses = len(courses)
    completed_courses = len([c for c in courses if c.get('completed', False)])
    ongoing_courses = total_courses - completed_courses
    
    bookmarked_courses = user.get('bookmarked_courses', [])
    quiz_history = user.get('quiz_history', [])
    has_assessment_history = bool(quiz_history)
    if not has_assessment_history:
        latest_file_result = get_latest_assessment_from_file(user.get('email'))
        if latest_file_result:
            has_assessment_history = True

    return render_template('my_courses.html',
                           user=user,
                           courses=courses,
                           total_courses=total_courses,
                           completed_courses=completed_courses,
                           ongoing_courses=ongoing_courses,
                           bookmarked_courses=bookmarked_courses,
                           bookmarks_count=len(bookmarked_courses),
                           has_assessment_history=has_assessment_history)

@main.route('/add-course/<int:course_index>')
@login_required
def add_course(course_index):
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    recommended_courses = session.get('recommended_courses', [])

    if course_index < len(recommended_courses):
        course = recommended_courses[course_index].copy()
        course['enrolled_date'] = datetime.datetime.now()
        course['completed'] = False
        course['completion_percentage'] = 0
        course['videos_progress'] = {
            video['url']: {
                'title': video['title'],
                'watched': False,
                'watch_time': 0,
                'last_position': 0,
                'completed': False
            } for video in course.get('videos', [])
        }
        
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$push': {'courses': course}}
        )

        flash(f'Course "{course["title"]}" added to your learning path!', 'success')
    else:
        flash('Course not found!', 'error')

    return redirect(url_for('main.dashboard'))

@main.route('/course/<int:course_index>')
@login_required
def view_course(course_index):
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    courses = user.get('courses', [])
    
    if course_index < len(courses):
        course = courses[course_index]
        return render_template('course.html', 
                            course=course, 
                            course_index=course_index,
                            videos_progress=course.get('videos_progress', {}),
                            is_enrolled=True)
    
    flash('Course not found!', 'error')
    return redirect(url_for('main.dashboard'))

@main.route('/course/recommended/<int:course_index>')
@login_required
def view_course_recommended(course_index):
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    recommended_courses = session.get('recommended_courses', [])
    
    if not recommended_courses or course_index >= len(recommended_courses):
        flash('Recommended course not found!', 'error')
        return redirect(url_for('main.dashboard'))
    
    course = recommended_courses[course_index].copy()
    user_courses = user.get('courses', [])
    course_already_enrolled = False
    enrolled_course_index = -1
    
    for i, enrolled_course in enumerate(user_courses):
        if enrolled_course.get('title') == course['title'] and enrolled_course.get('url') == course.get('url'):
            course_already_enrolled = True
            enrolled_course_index = i
            break
    
    if course_already_enrolled:
        enrolled_course = user_courses[enrolled_course_index]
        return render_template('course.html', 
                            course=enrolled_course, 
                            course_index=enrolled_course_index,
                            videos_progress=enrolled_course.get('videos_progress', {}),
                            is_enrolled=True)
    
    if isinstance(course.get('url'), str):
        video_url = course['url']
        if not video_url or '?embeds_referring' in video_url or not ('youtube.com/watch?v=' in video_url or 'youtu.be/' in video_url):
            video_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        
        try:
            if 'youtube.com' in video_url:
                video_id = video_url.split('v=')[1].split('&')[0]
            elif 'youtu.be' in video_url:
                video_id = video_url.split('/')[-1].split('?')[0]
            else:
                video_id = None
                
            if video_id and len(video_id) == 11:
                video_url = f'https://www.youtube.com/watch?v={video_id}'
            else:
                video_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        except Exception:
            video_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        
        course['videos'] = [{
            'title': course['title'],
            'url': video_url,
            'duration': course.get('duration', ''),
        }]
    
    course['enrolled_date'] = datetime.datetime.now()
    course['completed'] = False
    course['completion_percentage'] = 0
    course['videos_progress'] = {
        video['url']: {
            'title': video['title'],
            'watched': False,
            'watch_time': 0,
            'last_position': 0,
            'completed': False
        } for video in course.get('videos', [])
    }
    
    mongo.db.users.update_one(
        {'_id': ObjectId(session['user_id'])},
        {'$push': {'courses': course}}
    )
    
    updated_user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    new_course_index = len(updated_user.get('courses', [])) - 1
    
    flash(f'Course "{course["title"]}" has been added to your learning path!', 'success')
    
    return render_template('course.html', 
                        course=course, 
                        course_index=new_course_index,
                        videos_progress=course.get('videos_progress', {}),
                        is_enrolled=True)

@main.route('/api/dismiss-recommendation', methods=['POST'])
@login_required
def dismiss_recommendation():
    try:
        data = request.get_json()
        course_index = data.get('course_index')
        
        if course_index is None:
            return jsonify({'success': False, 'error': 'Course index required'})
        
        recommended_courses = session.get('recommended_courses', [])
        
        if course_index < 0 or course_index >= len(recommended_courses):
            return jsonify({'success': False, 'error': 'Invalid course index'})
        
        recommended_courses.pop(course_index)
        session['recommended_courses'] = recommended_courses
        session.modified = True
        
        return jsonify({'success': True, 'message': 'Recommendation dismissed'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@main.route('/api/remove-course', methods=['POST'])
@login_required
def remove_course():
    try:
        data = request.get_json()
        course_index = data.get('course_index')
        
        if course_index is None:
            return jsonify({'success': False, 'error': 'Course index required'})
        
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        courses = user.get('courses', [])
        
        if course_index < 0 or course_index >= len(courses):
            return jsonify({'success': False, 'error': 'Invalid course index'})
        
        removed_course = courses[course_index]
        course_title = removed_course.get('title', 'Unknown')
        
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$pull': {'courses': removed_course}}
        )
        
        return jsonify({
            'success': True, 
            'message': f'Course "{course_title}" removed successfully'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@main.route('/debug/session')
@login_required
def debug_session():
    if not current_app.debug:
        return "Debug mode only", 403
    
    session_data = {
        'recommended_courses_count': len(session.get('recommended_courses', [])),
        'recommended_courses': session.get('recommended_courses', []),
        'session_keys': list(session.keys())
    }
    
    return jsonify(session_data)

@main.route('/update-video-progress', methods=['POST'])
@login_required
def update_video_progress():
    try:
        course_index = int(request.form.get('course_index'))
        raw_video_url = request.form.get('video_url')
        video_url = canonical_youtube_url(raw_video_url) or raw_video_url
        current_time = float(request.form.get('current_time', 0))
        duration = float(request.form.get('duration', 0))
        is_completed = request.form.get('completed') == 'true'

        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        courses = user.get('courses', [])
        if course_index < len(courses):
            course = courses[course_index]
            
            if 'videos_progress' not in course:
                course['videos_progress'] = {}
            
            if video_url not in course['videos_progress']:
                course['videos_progress'][video_url] = {
                    'watch_time': 0,
                    'last_position': 0,
                    'completed': False
                }
            
            video_is_completed = is_completed or (duration > 0 and current_time >= (duration - 1))
            
            course['videos_progress'][video_url].update({
                'watch_time': current_time,
                'last_position': current_time,
                'completed': video_is_completed
            })

            declared_urls = []
            for v in course.get('videos', []):
                url = canonical_youtube_url(v.get('url') or '')
                if url:
                    declared_urls.append(url)

            if declared_urls:
                filtered_progress = {}
                for url in declared_urls:
                    if url in course['videos_progress']:
                        filtered_progress[url] = course['videos_progress'][url]
                    else:
                        filtered_progress[url] = {'watch_time': 0, 'last_position': 0, 'completed': False}
                course['videos_progress'] = filtered_progress
                
                total_videos = len(declared_urls)
                
                if total_videos == 1:
                    if duration > 0:
                        raw_progress = (current_time / duration) * 100
                        progress_percentage = round(raw_progress / 12.5) * 12.5
                        if current_time < (duration - 1):
                            progress_percentage = min(progress_percentage, 87.5)
                        else:
                            progress_percentage = 100
                        course['completion_percentage'] = progress_percentage
                    else:
                        course['completion_percentage'] = 0
                else:
                    completed_videos = len([v for v in course['videos_progress'].values() if v['completed']])
                    course['completion_percentage'] = (completed_videos / total_videos) * 100
            else:
                total_videos = len(course['videos_progress'])
                if total_videos > 0:
                    if duration > 0:
                        raw_progress = (current_time / duration) * 100
                        progress_percentage = round(raw_progress / 12.5) * 12.5
                        if current_time < (duration - 1):
                            progress_percentage = min(progress_percentage, 87.5)
                        else:
                            progress_percentage = 100
                        course['completion_percentage'] = progress_percentage
                    else:
                        completed_videos = len([v for v in course['videos_progress'].values() if v['completed']])
                        course['completion_percentage'] = (completed_videos / total_videos) * 100
                else:
                    course['completion_percentage'] = 0
            
            if course['completion_percentage'] >= 100 and not course.get('completed'):
                course['completed'] = True
                course['completion_date'] = datetime.datetime.now()

                user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

                certificate_code = generate_unique_certificate_id()
                certificate = {
                    'certificate_id': certificate_code,
                    'certificate_code': certificate_code,
                    'course_title': course['title'],
                    'instructor': course.get('instructor', 'Expert Instructor'),
                    'completion_date': datetime.datetime.now(),
                    'issued_date': datetime.datetime.now(),
                    'learning_goal': user.get('learning_goal', 'General Learning')
                }

                mongo.db.users.update_one(
                    {'_id': ObjectId(session['user_id'])},
                    {
                        '$set': {f'courses.{course_index}': course},
                        '$push': {'certificates': certificate}
                    }
                )

                return jsonify({
                    'status': 'success',
                    'progress': course['completion_percentage'],
                    'completed': True,
                    'certificate': certificate_code
                })

            mongo.db.users.update_one(
                {'_id': ObjectId(session['user_id'])},
                {'$set': {f'courses.{course_index}': course}}
            )

            return jsonify({
                'status': 'success',
                'progress': course['completion_percentage']
            })

        recommended_courses = session.get('recommended_courses', [])
        if recommended_courses and course_index < len(recommended_courses):
            if 'course_progress' not in session:
                session['course_progress'] = {}
            
            course_key = f"course_{course_index}"
            if course_key not in session['course_progress']:
                session['course_progress'][course_key] = {'videos_progress': {}}
            
            if video_url not in session['course_progress'][course_key]['videos_progress']:
                session['course_progress'][course_key]['videos_progress'][video_url] = {
                    'watch_time': 0,
                    'last_position': 0,
                    'completed': False
                }
            
            is_video_completed = is_completed or (duration > 0 and current_time >= (duration - 1))
            
            session['course_progress'][course_key]['videos_progress'][video_url].update({
                'watch_time': current_time,
                'last_position': current_time,
                'completed': is_video_completed
            })
            
            if duration > 0 and duration != float('inf') and math.isfinite(duration):
                raw_progress = (current_time / duration) * 100
                progress_percentage = round(raw_progress / 12.5) * 12.5
                if current_time < (duration - 1):
                    progress_percentage = min(progress_percentage, 87.5)
                else:
                    progress_percentage = 100.0
            else:
                progress_percentage = 0
            
            progress_percentage = max(0, min(100, progress_percentage))
            
            return jsonify({
                'status': 'success',
                'progress': progress_percentage,
                'completed': is_video_completed and progress_percentage >= 100
            })

        return jsonify({'status': 'error', 'message': 'Course not found'}), 400

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@main.route('/update-progress/<int:course_index>/<int:module_index>')
@login_required
def update_progress(course_index, module_index):
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    courses = user.get('courses', [])

    if course_index < len(courses):
        course = courses[course_index]
        modules = course['modules']

        if module_index < len(modules):
            module_name = modules[module_index]
            course['progress'][module_name] = not course['progress'].get(module_name, False)

            completed_modules = sum(1 for completed in course['progress'].values() if completed)
            course['completion_percentage'] = (completed_modules / len(modules)) * 100

            if course['completion_percentage'] == 100 and not course.get('completed'):
                course['completed'] = True
                course['completion_date'] = datetime.datetime.now()

                user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

                certificate_code = generate_unique_certificate_id()
                certificate = {
                    'certificate_id': certificate_code,
                    'certificate_code': certificate_code,
                    'course_title': course['title'],
                    'instructor': course.get('instructor', 'Expert Instructor'),
                    'completion_date': datetime.datetime.now(),
                    'issued_date': datetime.datetime.now(),
                    'learning_goal': user.get('learning_goal', 'General Learning')
                }

                mongo.db.users.update_one(
                    {'_id': ObjectId(session['user_id'])},
                    {
                        '$set': {f'courses.{course_index}': course},
                        '$push': {'certificates': certificate}
                    }
                )

                flash(f'Congratulations! You completed "{course["title"]}" and earned a certificate!', 'success')
            else:
                mongo.db.users.update_one(
                    {'_id': ObjectId(session['user_id'])},
                    {'$set': {f'courses.{course_index}': course}}
                )
                flash(f'Progress updated for "{module_name}"!', 'success')

    return redirect(url_for('main.view_course', course_index=course_index))

@main.route('/bookmark-course', methods=['POST'])
@login_required
def bookmark_course():
    try:
        data = request.get_json()
        course_data = {
            'title': data.get('title'),
            'instructor': data.get('instructor', 'Expert Instructor'),
            'url': data.get('url'),
            'duration': data.get('duration', ''),
            'topics': data.get('topics', []),
            'description': data.get('description', ''),
            'bookmarked_date': datetime.datetime.now()
        }
        
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        bookmarks = user.get('bookmarked_courses', [])
        
        if any(b.get('url') == course_data['url'] for b in bookmarks):
            return jsonify({'status': 'error', 'message': 'Course already bookmarked'})
        
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$push': {'bookmarked_courses': course_data}}
        )
        
        return jsonify({'status': 'success', 'message': 'Course bookmarked successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@main.route('/remove-bookmark', methods=['POST'])
@login_required
def remove_bookmark():
    try:
        data = request.get_json()
        course_url = data.get('url')
        
        if not course_url:
            return jsonify({'status': 'error', 'message': 'Course URL required'})
        
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$pull': {'bookmarked_courses': {'url': course_url}}}
        )
        
        return jsonify({'status': 'success', 'message': 'Bookmark removed successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@main.route('/api/enroll-from-bookmark', methods=['POST'])
@login_required
def enroll_from_bookmark():
    try:
        data = request.get_json()
        
        required_fields = ['title', 'url']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'status': 'error', 'message': f'Missing required field: {field}'}), 400
        
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        courses = user.get('courses', [])
        
        for i, course in enumerate(courses):
            if course.get('url') == data['url']:
                return jsonify({'status': 'success', 'course_index': i, 'already_enrolled': True})
        
        course = {
            'title': data.get('title'),
            'instructor': data.get('instructor', 'Expert Instructor'),
            'url': data.get('url'),
            'duration': data.get('duration', ''),
            'description': data.get('description', ''),
            'topics': data.get('topics', []),
            'platform': 'YouTube',
            'enrolled_date': datetime.datetime.now(),
            'completed': False,
            'completion_percentage': 0
        }
        
        if course.get('url'):
            video_url = course['url']
            course['videos'] = [{
                'title': course['title'],
                'url': video_url,
                'duration': course.get('duration', ''),
            }]
        
        course['videos_progress'] = {
            video['url']: {
                'title': video['title'],
                'watched': False,
                'watch_time': 0,
                'last_position': 0,
                'completed': False
            } for video in course.get('videos', [])
        }
        
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$push': {'courses': course}}
        )
        
        updated_user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        new_course_index = len(updated_user.get('courses', [])) - 1
        
        return jsonify({
            'status': 'success', 
            'course_index': new_course_index,
            'message': f'Enrolled in {course["title"]}'
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@main.route('/certificates')
@login_required
def certificates():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    certificates = user.get('certificates', [])
    return render_template('certificates.html', certificates=certificates)

@main.route('/test-results')
@login_required
def test_results():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    quiz_history = user.get('quiz_history', [])
    
    quiz_history_formatted = []
    for quiz in quiz_history:
        quiz_copy = quiz.copy()
        if quiz_copy.get('date'):
            quiz_copy['date'] = quiz_copy['date'].isoformat()
        quiz_history_formatted.append(quiz_copy)
    
    results_dir = os.path.join(os.getcwd(), 'Test Results')
    file_results = []
    
    if os.path.exists(results_dir):
        files = [f for f in os.listdir(results_dir) if f.endswith('.txt')]
        for filename in sorted(files, reverse=True):
            file_path = os.path.join(results_dir, filename)
            file_stats = os.stat(file_path)
            file_results.append({
                'filename': filename,
                'filepath': file_path,
                'date': datetime.datetime.fromtimestamp(file_stats.st_mtime),
                'size': file_stats.st_size
            })
    
    return render_template('test_results.html', 
                         quiz_history=quiz_history,
                         quiz_history_json=quiz_history_formatted,
                         file_results=file_results)

@main.route('/view-test-result/<path:filename>')
@login_required
def view_test_result(filename):
    results_dir = os.path.join(os.getcwd(), 'Test Results')
    filepath = os.path.join(results_dir, filename)
    
    if not filepath.startswith(results_dir):
        flash('Invalid file path!', 'error')
        return redirect(url_for('main.test_results'))
    
    if not os.path.exists(filepath):
        flash('Test result file not found!', 'error')
        return redirect(url_for('main.test_results'))
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return render_template('view_test_result.html', filename=filename, content=content)
    except Exception as e:
        flash(f'Error reading file: {str(e)}', 'error')
        return redirect(url_for('main.test_results'))

@main.route('/download-certificate/<certificate_code>')
@login_required
def download_certificate(certificate_code):
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    certificates = user.get('certificates', [])

    certificate = next((cert for cert in certificates if cert.get('certificate_code') == certificate_code or cert.get('certificate_id') == certificate_code), None)

    if not certificate:
        flash('Certificate not found!', 'error')
        return redirect(url_for('main.certificates'))

    course_title = certificate['course_title']
    courses = user.get('courses', [])
    corresponding_course = next((c for c in courses if c.get('title') == course_title), None)
    
    if corresponding_course and corresponding_course.get('instructor'):
        instructor_name = corresponding_course['instructor']
    elif certificate.get('instructor'):
        instructor_name = certificate['instructor']
    else:
        instructor_name = 'Expert Instructor'
    
    course_url = corresponding_course['url'] if corresponding_course and corresponding_course.get('url') else None

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    def draw_centered_text(canvas_obj, y_pos, text, font_name, font_size, color=None):
        if color:
            canvas_obj.setFillColor(color)
        canvas_obj.setFont(font_name, font_size)
        text_width = canvas_obj.stringWidth(text, font_name, font_size)
        x_pos = (width - text_width) / 2
        canvas_obj.drawString(x_pos, y_pos, text)

    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(4)
    p.rect(40, 40, width - 80, height - 80)
    p.setStrokeColor(Color(0.8, 0.8, 0.8))
    p.setLineWidth(1)
    p.rect(55, 55, width - 110, height - 110)

    draw_centered_text(p, height - 120, "CERTIFICATE OF COMPLETION", "Helvetica-Bold", 32, Color(0.2, 0.4, 0.8))

    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(2)
    line_y = height - 135
    p.line(width / 2 - 180, line_y, width / 2 + 180, line_y)

    draw_centered_text(p, height - 200, "This is to certify that", "Helvetica", 16, Color(0.3, 0.3, 0.3))

    user_name = user['name'].upper()
    draw_centered_text(p, height - 260, user_name, "Helvetica-Bold", 28, Color(0.1, 0.1, 0.1))

    p.setStrokeColor(Color(0.7, 0.7, 0.7))
    p.setLineWidth(1)
    p.setFont("Helvetica-Bold", 28)
    name_width = p.stringWidth(user_name, "Helvetica-Bold", 28)
    name_line_y = height - 275
    p.line(width / 2 - name_width / 2 - 15, name_line_y, width / 2 + name_width / 2 + 15, name_line_y)

    draw_centered_text(p, height - 320, "has successfully completed the course", "Helvetica", 16, Color(0.3, 0.3, 0.3))

    title_length = len(course_title)
    if title_length <= 40:
        title_font_size = 20
        title_lines = [course_title]
        base_y = height - 370
    elif title_length <= 70:
        title_font_size = 18
        p.setFont("Helvetica-Bold", title_font_size)
        if p.stringWidth(course_title, "Helvetica-Bold", title_font_size) <= (width - 120):
            title_lines = [course_title]
        else:
            words = course_title.split()
            lines, current_line = [], ""
            for word in words:
                test_line = current_line + (" " + word if current_line else word)
                if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 120):
                    current_line = test_line
                else:
                    if current_line: lines.append(current_line)
                    current_line = word
            if current_line: lines.append(current_line)
            title_lines = lines[:2]
        base_y = height - 370
    else:
        title_font_size = 16
        words = course_title.split()
        lines, current_line = [], ""
        p.setFont("Helvetica-Bold", title_font_size)
        for word in words:
            test_line = current_line + (" " + word if current_line else word)
            if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 100):
                current_line = test_line
            else:
                if current_line: lines.append(current_line)
                current_line = word
        if current_line: lines.append(current_line)
        title_lines = lines[:3]
        base_y = height - 360
    
    line_spacing = title_font_size + 5
    for i, line in enumerate(title_lines):
        y_position = base_y - (i * line_spacing)
        draw_centered_text(p, y_position, f'"{line}"' if i == 0 else line, "Helvetica-Bold", title_font_size, Color(0.2, 0.4, 0.8))
    
    instructor_y = base_y - (len(title_lines) * line_spacing) - 20
    instructor_text = f"by {instructor_name}"
    p.setFillColor(Color(0.3, 0.3, 0.3))
    p.setFont("Helvetica-Oblique", 13)
    text_width = p.stringWidth(instructor_text, "Helvetica-Oblique", 13)
    x_pos = (width - text_width) / 2
    p.drawString(x_pos, instructor_y, instructor_text)
    
    if course_url and ('youtube.com' in course_url or 'youtu.be' in course_url):
        link_rect = (x_pos, instructor_y - 2, x_pos + text_width, instructor_y + 13)
        p.linkURL(course_url, link_rect, relative=0)
        p.setStrokeColor(Color(0.3, 0.3, 0.3))
        p.setLineWidth(0.5)
        p.line(x_pos, instructor_y - 1, x_pos + text_width, instructor_y - 1)

    date_y = instructor_y - 45
    cert_id_y = date_y - 25
    completion_date = certificate['completion_date'].strftime("%B %d, %Y")
    draw_centered_text(p, date_y, f"Completed on: {completion_date}", "Helvetica", 14, Color(0.4, 0.4, 0.4))
    draw_centered_text(p, cert_id_y, f"Certificate ID: {certificate['certificate_code']}", "Helvetica", 12, Color(0.5, 0.5, 0.5))

    circle_y = (height - 120 + cert_id_y) / 2
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(100, circle_y, 18, fill=1)
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(width - 100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(width - 100, circle_y, 18, fill=1)

    draw_centered_text(p, 140, "Personalized Education Platform", "Helvetica-Bold", 13, Color(0.5, 0.5, 0.5))
    draw_centered_text(p, 120, "Empowering Learners Worldwide", "Helvetica-Oblique", 11, Color(0.6, 0.6, 0.6))

    p.setFillColor(Color(0.7, 0.7, 0.7))
    p.setFont("Helvetica", 7)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    p.drawString(50, 50, f"Generated: {timestamp}")

    p.setStrokeColor(Color(0.5, 0.5, 0.5))
    p.setLineWidth(1)
    sig_y = 220
    p.line(width / 2 - 100, sig_y, width / 2 + 100, sig_y)
    draw_centered_text(p, sig_y - 20, "Authorized Signature", "Helvetica", 9, Color(0.5, 0.5, 0.5))

    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name=f'certificate_{certificate_code}.pdf', mimetype='application/pdf')

@main.route('/admin/make-me-admin', methods=['POST', 'GET'])
@login_required
def make_me_admin():
    existing_admins = mongo.db.users.count_documents({'is_admin': True})
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

    if request.method == 'GET':
        return render_template('admin_make_me_admin.html', existing_admins=existing_admins)

    if existing_admins > 0 and not user.get('is_admin', False):
        flash('An admin already exists. Ask an admin to promote you.', 'error')
        return redirect(url_for('main.dashboard'))

    mongo.db.users.update_one({'_id': user['_id']}, {'$set': {'is_admin': True}})
    session['is_admin'] = True
    flash('You have been promoted to admin.', 'success')
    return redirect(url_for('main.admin_dashboard'))

@main.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_users = mongo.db.users.count_documents({'is_admin': {'$ne': True}})
    total_admins = mongo.db.users.count_documents({'is_admin': True})
    
    all_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    total_enrollments = sum(len(user.get('courses', [])) for user in all_users)
    total_completions = sum(len([c for c in user.get('courses', []) if c.get('completed')]) for user in all_users)
    total_certificates = sum(len(user.get('certificates', [])) for user in all_users)
    total_assessments = sum(len(user.get('quiz_history', [])) for user in all_users)
    
    goal_distribution = {}
    for user in all_users:
        goal = user.get('learning_goal', 'Not Set')
        goal_distribution[goal] = goal_distribution.get(goal, 0) + 1
    
    recent_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}).sort('created_at', -1).limit(5))
    
    recent_assessments = []
    for user in all_users:
        quiz_history = user.get('quiz_history', [])
        for quiz in quiz_history:
            recent_assessments.append({
                'user_name': user.get('name'),
                'user_email': user.get('email'),
                'learning_goal': quiz.get('learning_goal'),
                'score': quiz.get('score'),
                'total': quiz.get('total'),
                'percentage': quiz.get('percentage'),
                'level': quiz.get('level'),
                'date': quiz.get('date')
            })
    
    recent_assessments.sort(key=lambda x: x.get('date', datetime.datetime.min), reverse=True)
    recent_assessments = recent_assessments[:10]

    return render_template('admin_dashboard.html',
                           total_users=total_users,
                           total_admins=total_admins,
                           total_enrollments=total_enrollments,
                           total_completions=total_completions,
                           total_certificates=total_certificates,
                           total_assessments=total_assessments,
                           goal_distribution=goal_distribution,
                           recent_users=recent_users,
                           recent_assessments=recent_assessments)

@main.route('/admin/users')
@admin_required
def admin_users():
    users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    return render_template('admin_users.html', users=users)

@main.route('/admin/test-results')
@admin_required
def admin_test_results():
    all_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    all_test_results = []
    
    for user in all_users:
        quiz_history = user.get('quiz_history', [])
        for quiz in quiz_history:
            quiz_copy = quiz.copy()
            quiz_copy['user_id'] = str(user['_id'])
            quiz_copy['user_name'] = user.get('name', 'Unknown')
            quiz_copy['user_email'] = user.get('email', 'Unknown')
            
            if quiz_copy.get('date'):
                quiz_copy['date_formatted'] = quiz_copy['date'].strftime('%B %d, %Y at %I:%M %p')
                quiz_copy['date_iso'] = quiz_copy['date'].isoformat()
            all_test_results.append(quiz_copy)
    
    all_test_results.sort(key=lambda x: x.get('date', datetime.datetime.min), reverse=True)
    
    results_dir = os.path.join(os.getcwd(), 'Test Results')
    file_results = []
    
    if os.path.exists(results_dir):
        files = [f for f in os.listdir(results_dir) if f.endswith('.txt')]
        for filename in sorted(files, reverse=True):
            file_path = os.path.join(results_dir, filename)
            file_stats = os.stat(file_path)
            file_results.append({
                'filename': filename,
                'filepath': file_path,
                'date': datetime.datetime.fromtimestamp(file_stats.st_mtime),
                'size': file_stats.st_size
            })
    
    return render_template('admin_test_results.html',
                         all_test_results=all_test_results,
                         file_results=file_results,
                         total_tests=len(all_test_results))

@main.route('/admin/certificates')
@admin_required
def admin_certificates():
    all_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    all_certificates = []
    
    for user in all_users:
        for cert in user.get('certificates', []):
            cert_copy = cert.copy()
            cert_copy['user_id'] = str(user['_id'])
            cert_copy['user_name'] = user.get('name', 'Unknown')
            cert_copy['user_email'] = user.get('email', 'Unknown')
            
            issued_date = cert_copy.get('issued_date') or cert_copy.get('completion_date')
            if issued_date:
                if isinstance(issued_date, str):
                    try:
                        cert_date = datetime.datetime.strptime(issued_date, '%Y-%m-%d')
                        cert_copy['issued_date_formatted'] = cert_date.strftime('%B %d, %Y')
                        cert_copy['issued_date_sort'] = cert_date
                    except:
                        cert_copy['issued_date_formatted'] = issued_date
                        cert_copy['issued_date_sort'] = datetime.datetime.min
                else:
                    cert_copy['issued_date_formatted'] = issued_date.strftime('%B %d, %Y')
                    cert_copy['issued_date_sort'] = issued_date
            else:
                cert_copy['issued_date_formatted'] = 'Unknown'
                cert_copy['issued_date_sort'] = datetime.datetime.min
            
            if not cert_copy.get('certificate_id'):
                cert_copy['certificate_id'] = cert_copy.get('certificate_code', 'Unknown')
            if not cert_copy.get('learning_goal'):
                cert_copy['learning_goal'] = user.get('learning_goal', 'Unknown')
            all_certificates.append(cert_copy)
    
    all_certificates.sort(key=lambda x: x.get('issued_date_sort', datetime.datetime.min), reverse=True)
    
    unique_goals = list(set(cert.get('learning_goal', 'Unknown') for cert in all_certificates))
    unique_goals.sort()
    
    return render_template('admin_certificates.html',
                         all_certificates=all_certificates,
                         unique_goals=unique_goals,
                         total_certificates=len(all_certificates),
                         users_with_certs=len([u for u in all_users if u.get('certificates')]),
                         total_users=len(all_users))

@main.route('/admin/revoke-certificate', methods=['POST'])
@admin_required
def admin_revoke_certificate():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        certificate_id = data.get('certificate_id')
        
        if not user_id or not certificate_id:
            return jsonify({'success': False, 'message': 'Missing user_id or certificate_id'}), 400
        
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        certificates = user.get('certificates', [])
        updated_certificates = [c for c in certificates if c.get('certificate_id') != certificate_id]
        
        if len(certificates) == len(updated_certificates):
            return jsonify({'success': False, 'message': 'Certificate not found'}), 404
        
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'certificates': updated_certificates}}
        )
        
        return jsonify({'success': True, 'message': f'Certificate {certificate_id} has been revoked successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@main.route('/admin/view-certificate/<user_id>/<certificate_id>')
@admin_required
def admin_view_certificate(user_id, certificate_id):
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found!', 'error')
        return redirect(url_for('main.admin_certificates'))
    
    certificate = next((cert for cert in user.get('certificates', []) if cert.get('certificate_code') == certificate_id or cert.get('certificate_id') == certificate_id), None)
    if not certificate:
        flash('Certificate not found!', 'error')
        return redirect(url_for('main.admin_certificates'))

    course_title = certificate.get('course_title', 'Unknown Course')
    corresponding_course = next((c for c in user.get('courses', []) if c.get('title') == course_title), None)
    
    instructor_name = corresponding_course.get('instructor') if corresponding_course and corresponding_course.get('instructor') else certificate.get('instructor', 'Expert Instructor')
    course_url = corresponding_course.get('url') if corresponding_course else None

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    def draw_centered_text(canvas_obj, y_pos, text, font_name, font_size, color=None):
        if color: canvas_obj.setFillColor(color)
        canvas_obj.setFont(font_name, font_size)
        text_width = canvas_obj.stringWidth(text, font_name, font_size)
        canvas_obj.drawString((width - text_width) / 2, y_pos, text)

    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(4)
    p.rect(40, 40, width - 80, height - 80)
    p.setStrokeColor(Color(0.8, 0.8, 0.8))
    p.setLineWidth(1)
    p.rect(55, 55, width - 110, height - 110)

    draw_centered_text(p, height - 120, "CERTIFICATE OF COMPLETION", "Helvetica-Bold", 32, Color(0.2, 0.4, 0.8))

    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(2)
    p.line(width / 2 - 180, height - 135, width / 2 + 180, height - 135)

    draw_centered_text(p, height - 200, "This is to certify that", "Helvetica", 16, Color(0.3, 0.3, 0.3))

    user_name = user['name'].upper()
    draw_centered_text(p, height - 260, user_name, "Helvetica-Bold", 28, Color(0.1, 0.1, 0.1))

    p.setStrokeColor(Color(0.7, 0.7, 0.7))
    p.setLineWidth(1)
    p.setFont("Helvetica-Bold", 28)
    name_width = p.stringWidth(user_name, "Helvetica-Bold", 28)
    p.line(width / 2 - name_width / 2 - 15, height - 275, width / 2 + name_width / 2 + 15, height - 275)

    draw_centered_text(p, height - 320, "has successfully completed the course", "Helvetica", 16, Color(0.3, 0.3, 0.3))

    title_length = len(course_title)
    if title_length <= 40:
        title_font_size = 20
        title_lines = [course_title]
        base_y = height - 370
    elif title_length <= 70:
        title_font_size = 18
        p.setFont("Helvetica-Bold", title_font_size)
        if p.stringWidth(course_title, "Helvetica-Bold", title_font_size) <= (width - 120):
            title_lines = [course_title]
        else:
            words = course_title.split()
            lines, current_line = [], ""
            for word in words:
                test_line = current_line + (" " + word if current_line else word)
                if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 120):
                    current_line = test_line
                else:
                    if current_line: lines.append(current_line)
                    current_line = word
            if current_line: lines.append(current_line)
            title_lines = lines[:2]
        base_y = height - 370
    else:
        title_font_size = 16
        words = course_title.split()
        lines, current_line = [], ""
        p.setFont("Helvetica-Bold", title_font_size)
        for word in words:
            test_line = current_line + (" " + word if current_line else word)
            if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 100):
                current_line = test_line
            else:
                if current_line: lines.append(current_line)
                current_line = word
        if current_line: lines.append(current_line)
        title_lines = lines[:3]
        base_y = height - 360

    line_spacing = title_font_size + 5
    for i, line in enumerate(title_lines):
        draw_centered_text(p, base_y - (i * line_spacing), f'"{line}"' if i == 0 else line, "Helvetica-Bold", title_font_size, Color(0.2, 0.4, 0.8))

    instructor_y = base_y - (len(title_lines) * line_spacing) - 20
    instructor_text = f"by {instructor_name}"
    p.setFillColor(Color(0.3, 0.3, 0.3))
    p.setFont("Helvetica-Oblique", 13)
    text_width = p.stringWidth(instructor_text, "Helvetica-Oblique", 13)
    x_pos = (width - text_width) / 2
    p.drawString(x_pos, instructor_y, instructor_text)

    if course_url and ('youtube.com' in course_url or 'youtu.be' in course_url):
        link_rect = (x_pos, instructor_y - 2, x_pos + text_width, instructor_y + 13)
        p.linkURL(course_url, link_rect, relative=0)
        p.setStrokeColor(Color(0.3, 0.3, 0.3))
        p.setLineWidth(0.5)
        p.line(x_pos, instructor_y - 1, x_pos + text_width, instructor_y - 1)

    date_y = instructor_y - 45
    cert_id_y = date_y - 25
    completion_date = certificate['completion_date'].strftime("%B %d, %Y")
    draw_centered_text(p, date_y, f"Completed on: {completion_date}", "Helvetica", 14, Color(0.4, 0.4, 0.4))
    draw_centered_text(p, cert_id_y, f"Certificate ID: {certificate['certificate_code']}", "Helvetica", 12, Color(0.5, 0.5, 0.5))

    circle_y = (height - 120 + cert_id_y) / 2
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(100, circle_y, 18, fill=1)
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(width - 100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(width - 100, circle_y, 18, fill=1)

    draw_centered_text(p, 140, "Personalized Education Platform", "Helvetica-Bold", 13, Color(0.5, 0.5, 0.5))
    draw_centered_text(p, 120, "Empowering Learners Worldwide", "Helvetica-Oblique", 11, Color(0.6, 0.6, 0.6))

    p.setFillColor(Color(0.7, 0.7, 0.7))
    p.setFont("Helvetica", 7)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    p.drawString(50, 50, f"Generated: {timestamp}")

    p.setStrokeColor(Color(0.5, 0.5, 0.5))
    p.setLineWidth(1)
    p.line(width / 2 - 100, 220, width / 2 + 100, 220)
    draw_centered_text(p, 200, "Authorized Signature", "Helvetica", 9, Color(0.5, 0.5, 0.5))

    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=False, download_name=f'certificate_{certificate_id}.pdf', mimetype='application/pdf')

@main.route('/admin/users/<user_id>', methods=['GET'])
@admin_required
def admin_user_detail(user_id):
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        payload = {
            'id': str(user['_id']),
            'name': user.get('name'),
            'email': user.get('email'),
            'learning_goal': user.get('learning_goal'),
            'skill_level': user.get('skill_level', 0),
            'courses_count': len(user.get('courses', [])),
            'certificates_count': len(user.get('certificates', [])),
            'created_at': user.get('created_at').strftime('%Y-%m-%d %H:%M') if user.get('created_at') and hasattr(user.get('created_at'), 'strftime') else (str(user.get('created_at')) if user.get('created_at') else None),
            'is_admin': bool(user.get('is_admin', False)),
        }
        return jsonify({'success': True, 'user': payload})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@main.route('/admin/users/<user_id>/edit', methods=['POST'])
@admin_required
def admin_user_edit(user_id):
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        learning_goal = (data.get('learning_goal') or '').strip() or None
        try:
            skill_level = float(data.get('skill_level')) if data.get('skill_level') is not None else None
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid skill level'}), 400

        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if user.get('is_admin'):
            return jsonify({'success': False, 'message': 'Cannot edit admin user via this page'}), 403

        if email and email != user.get('email'):
            if mongo.db.users.find_one({'email': email, '_id': {'$ne': ObjectId(user_id)}}):
                return jsonify({'success': False, 'message': 'Email already in use'}), 400

        updates = {}
        if name: updates['name'] = name
        if email: updates['email'] = email
        updates['learning_goal'] = learning_goal
        if skill_level is not None:
            updates['skill_level'] = max(0.0, min(100.0, skill_level))

        if not updates:
            return jsonify({'success': False, 'message': 'No changes provided'}), 400

        mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': updates})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@main.route('/admin/users/<user_id>/delete', methods=['POST'])
@admin_required
def admin_user_delete(user_id):
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if user.get('is_admin', False):
            return jsonify({'success': False, 'message': 'Cannot delete an admin user'}), 403

        if str(user.get('_id')) == session.get('user_id'):
            return jsonify({'success': False, 'message': 'You cannot delete your own account here'}), 400

        mongo.db.users.delete_one({'_id': ObjectId(user_id)})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@main.route('/api/dashboard-data')
@login_required
def dashboard_data():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    quiz_history = user.get('quiz_history', [])
    quiz_data = {
        'labels': [q['date'].strftime('%m/%d') for q in quiz_history],
        'scores': [q['percentage'] for q in quiz_history]
    }

    courses = user.get('courses', [])
    completed = len([c for c in courses if c.get('completed', False)])
    in_progress = len(courses) - completed

    course_data = {
        'labels': ['Completed', 'In Progress'],
        'data': [completed, in_progress]
    }

    return jsonify({
        'quiz_data': quiz_data,
        'course_data': course_data
    })

@main.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        
        if name and email:
            mongo.db.users.update_one(
                {'_id': ObjectId(session['user_id'])},
                {'$set': {'name': name, 'email': email}}
            )
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('main.profile'))
        else:
            flash('Name and Email are required!', 'error')
            
    return render_template('profile.html', user=user)
