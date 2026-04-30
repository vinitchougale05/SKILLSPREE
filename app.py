from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
import bcrypt
import secrets
import datetime
import json
import math
from bson import ObjectId
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color
from reportlab.lib import colors
import io
import os
import requests
import google.generativeai as genai
import re
from typing import Optional

def validate_youtube_video_id(video_id):
    """
    Validate if a YouTube video ID has the correct format
    Returns True if valid format, False otherwise
    Note: We can't check if it's embeddable without making an API call,
    so we just validate the format and let the frontend handle embed errors
    """
    if not video_id or len(video_id) != 11:
        return False
    # Check if it contains only valid YouTube ID characters
    if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        return True
    return False


def search_youtube_videos(search_query, api_key="AIzaSyAQvd9bhuAFHmzxnpg7xqxhA_avSoDJqnE", max_results=3):
    """
    Search for YouTube videos using YouTube Data API v3 Search endpoint
    
    Args:
        search_query: Search term (e.g., "freeCodeCamp Python for beginners")
        api_key: YouTube Data API v3 key
        max_results: Maximum number of results to return (default: 3)
    
    Returns:
        List of video info dicts with 'title', 'video_id', 'channel', 'description'
        Returns empty list if API is not enabled or search fails
    """
    try:
        # Use YouTube Search API to find videos
        search_url = f"https://www.googleapis.com/youtube/v3/search"
        params = {
            'part': 'snippet',
            'q': search_query,
            'type': 'video',
            'videoDuration': 'long',  # Only long videos (>20 minutes)
            'maxResults': max_results,
            'key': api_key,
            'order': 'relevance'  # Most relevant first
        }
        
        response = requests.get(search_url, params=params, timeout=5)
        
        if response.status_code == 403:
            print(f"Debug - YouTube API not enabled! Enable it at: https://console.developers.google.com/apis/api/youtube.googleapis.com")
            return []
        
        if response.status_code != 200:
            print(f"Debug - YouTube Search API error: {response.status_code}")
            return []
        
        data = response.json()
        videos = []
        
        for item in data.get('items', []):
            video_id = item['id'].get('videoId')
            snippet = item.get('snippet', {})
            
            if video_id:
                videos.append({
                    'video_id': video_id,
                    'title': snippet.get('title', ''),
                    'channel': snippet.get('channelTitle', ''),
                    'description': snippet.get('description', '')
                })
        
        print(f"Debug - YouTube Search found {len(videos)} videos for: '{search_query}'")
        return videos
        
    except Exception as e:
        print(f"Debug - Error searching YouTube: {e}")
        return []


def verify_youtube_video_exists(video_id, api_key="AIzaSyAQvd9bhuAFHmzxnpg7xqxhA_avSoDJqnE"):
    """
    Verify if a YouTube video actually exists and is embeddable using YouTube Data API v3
    
    Args:
        video_id: 11-character YouTube video ID
        api_key: YouTube Data API v3 key (reusing Gemini API key or use dedicated key)
    
    Returns:
        dict with 'exists', 'embeddable', 'title', 'duration' if video exists, None otherwise
    
    NOTE: YouTube Data API v3 must be enabled in Google Cloud Console for this to work!
    If API returns 403, enable it at: https://console.developers.google.com/apis/api/youtube.googleapis.com
    """
    try:
        url = f"https://www.googleapis.com/youtube/v3/videos?part=status,snippet,contentDetails&id={video_id}&key={api_key}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 403:
            print(f"Debug - YouTube API not enabled! Enable it at: https://console.developers.google.com/apis/api/youtube.googleapis.com")
            print(f"Debug - Falling back to format-only validation (videos may not work!)")
            return None
        
        if response.status_code != 200:
            print(f"Debug - YouTube API error: {response.status_code}")
            return None
        
        data = response.json()
        
        # Check if video exists
        if not data.get('items'):
            print(f"Debug - Video {video_id} not found on YouTube")
            return None
        
        video_info = data['items'][0]
        status = video_info.get('status', {})
        snippet = video_info.get('snippet', {})
        content_details = video_info.get('contentDetails', {})
        
        # Check if video is embeddable and public
        is_embeddable = status.get('embeddable', False)
        is_public = status.get('privacyStatus') == 'public'
        
        if not is_public:
            print(f"Debug - Video {video_id} is not public (status: {status.get('privacyStatus')})")
            return None
        
        if not is_embeddable:
            print(f"Debug - Video {video_id} is not embeddable")
            return None
        
        return {
            'exists': True,
            'embeddable': True,
            'title': snippet.get('title', ''),
            'duration': content_details.get('duration', ''),
            'channel': snippet.get('channelTitle', '')
        }
        
    except Exception as e:
        print(f"Debug - Error verifying video {video_id}: {e}")
        return None


def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    """Extract a 11-char YouTube video ID from a URL or return the ID if it's already an ID."""
    if not url_or_id:
        return None
    candidate = url_or_id.strip()
    # If already looks like a video id
    if re.match(r'^[a-zA-Z0-9_-]{11}$', candidate):
        return candidate
    try:
        # Try parsing as URL
        if 'youtu.be/' in candidate:
            vid = candidate.split('youtu.be/')[-1].split('?')[0].split('/')[0]
            return vid if re.match(r'^[a-zA-Z0-9_-]{11}$', vid) else None
        if 'youtube.com' in candidate:
            # Check v= param
            q = candidate.split('?', 1)
            if len(q) > 1:
                params = q[1]
                for part in params.split('&'):
                    if part.startswith('v='):
                        vid = part[2:]
                        return vid if re.match(r'^[a-zA-Z0-9_-]{11}$', vid) else None
        return None
    except Exception:
        return None


def canonical_youtube_url(url_or_id: str) -> Optional[str]:
    """Return a canonical YouTube watch URL (https://youtube.com/watch?v=ID) if an ID can be extracted."""
    vid = extract_youtube_video_id(url_or_id)
    return f"https://youtube.com/watch?v={vid}" if vid else None

genai.configure(api_key="AIzaSyAQvd9bhuAFHmzxnpg7xqxhA_avSoDJqnE")

# Configure Gemini model
model = genai.GenerativeModel('gemini-2.5-flash')

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['MONGO_URI'] = 'mongodb://localhost:27017/education_platform'

# Initialize MongoDB
mongo = PyMongo(app)

def generate_unique_certificate_id():
    """Generate a unique certificate ID that doesn't exist in the database"""
    while True:
        certificate_code = secrets.token_hex(8).upper()
        # Check if this ID exists in any user's certificates
        existing = mongo.db.users.find_one({'certificates.certificate_id': certificate_code})
        if not existing:
            return certificate_code

@app.context_processor
def inject_admin_flags():
    """Inject common admin-related flags into all templates."""
    try:
        admin_exists = mongo.db.users.count_documents({'is_admin': True}) > 0
    except Exception:
        admin_exists = False
    return {
        'is_admin': session.get('is_admin', False),
        'admin_exists': admin_exists,
    }

def add_to_bookmarks(user_id, course_url):
    """Add a course URL to user's bookmarks"""
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$addToSet': {'bookmarked_courses': course_url}}
    )

def save_test_results_to_file(user, quiz_result):
    """Save test results to a local text file in Test Results folder"""
    import os
    
    try:
        # Create Test Results directory if it doesn't exist
        results_dir = os.path.join(os.getcwd(), 'Test Results')
        if not os.path.exists(results_dir):
            os.makedirs(results_dir)
        
        # Format filename with date and time
        test_date = quiz_result['date']
        filename = test_date.strftime('%Y-%m-%d_%H-%M-%S') + '_assessment.txt'
        filepath = os.path.join(results_dir, filename)
        
        # Prepare content
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
        
        # Add detailed results
        for i, result in enumerate(quiz_result.get('detailed_results', []), 1):
            content.append(f"Question {i}: [{result.get('difficulty', 'N/A').upper()}]")
            content.append(f"{result['question']}\n")
            
            # Show all options
            for j, option in enumerate(result['options']):
                marker = ""
                if j == result['user_answer'] and j == result['correct_answer']:
                    marker = " ✓ [YOUR ANSWER - CORRECT]"
                elif j == result['user_answer']:
                    marker = " ✗ [YOUR ANSWER - INCORRECT]"
                elif j == result['correct_answer']:
                    marker = " ✓ [CORRECT ANSWER]"
                
                content.append(f"  {chr(65+j)}. {option}{marker}")
            
            content.append("")  # Blank line between questions
        
        content.append("=" * 80)
        content.append(f"End of Assessment Results - Generated on {test_date.strftime('%Y-%m-%d %H:%M:%S')}")
        content.append("=" * 80)
        
        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content))
        
        print(f"Debug - Test results saved to: {filepath}")
        
    except Exception as e:
        print(f"Error saving test results to file: {e}")

def get_latest_assessment_from_file(user_email):
    """Retrieve the latest assessment result from text files for a specific user"""
    results_dir = os.path.join(os.getcwd(), 'Test Results')
    if not os.path.exists(results_dir):
        return None
    
    # Look in both root Test Results and 'old' subdirectory if it exists
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
        
    # Sort by filename (which starts with date) descending
    # Since paths are different, we should sort by basename
    all_files.sort(key=lambda x: os.path.basename(x), reverse=True)
    
    for filepath in all_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                # Check if this file belongs to the user (case insensitive)
                # Strip whitespace from both email and content search
                clean_email = user_email.strip()
                if clean_email and f"Email: {clean_email}".lower() in content.lower():
                    return parse_assessment_file(content)
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue
            
    return None

def parse_assessment_file(content):
    """Parse assessment text file content into a dictionary"""
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

def generate_quiz_questions(learning_goal, num_questions=10):
    """
    Generate quiz questions dynamically using Gemini API based on learning goal
    """
    prompt = f"""
    Generate exactly {num_questions} multiple-choice quiz questions to properly assess a candidate's knowledge in {learning_goal}.
    
    CRITICAL REQUIREMENTS - DIFFICULTY DISTRIBUTION:
    You MUST create questions with the following difficulty breakdown:
    - 3-4 EASY questions (basic concepts, terminology, simple syntax)
    - 3-4 MEDIUM questions (understanding of concepts, practical application)
    - 2-3 HARD questions (advanced concepts, problem-solving, best practices)
    
    EASY Questions should test:
    - Basic terminology and definitions
    - Simple syntax or fundamental concepts
    - What a beginner would know after first introduction
    
    MEDIUM Questions should test:
    - Understanding of how concepts work together
    - Practical scenarios and common use cases
    - Intermediate-level knowledge
    
    HARD Questions should test:
    - Advanced concepts and edge cases
    - Performance optimization or best practices
    - Complex problem-solving scenarios
    - What an experienced developer would know
    
    Additional Requirements:
    1. Each question must have exactly 4 options
    2. Include a mix of theoretical and practical questions
    3. Ensure questions progressively increase in difficulty
    4. All questions must be relevant to {learning_goal}
    
    Return ONLY a valid JSON array with this EXACT structure:
    [
        {{
            "question": "Question text here?",
            "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
            "correct": 0,
            "difficulty": "easy"
        }},
        {{
            "question": "Question text here?",
            "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
            "correct": 1,
            "difficulty": "medium"
        }},
        {{
            "question": "Question text here?",
            "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
            "correct": 2,
            "difficulty": "hard"
        }}
    ]
    
    Where:
    - "correct" is the index (0-3) of the correct option
    - "difficulty" is one of: "easy", "medium", or "hard"
    
    Do not include any text before or after the JSON array.
    ENSURE you have a balanced mix of difficulties as specified above.
    """
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        print(f"Debug - Quiz generation response received for {learning_goal}")
        
        # Clean the response to extract JSON
        if not response_text.startswith('['):
            start = response_text.find('[')
            end = response_text.rfind(']') + 1
            if start != -1 and end != 0:
                response_text = response_text[start:end]
        
        questions = json.loads(response_text)
        
        # Validate the structure
        valid_questions = []
        for q in questions:
            if (isinstance(q, dict) and 
                'question' in q and 
                'options' in q and 
                'correct' in q and
                isinstance(q['options'], list) and
                len(q['options']) == 4 and
                isinstance(q['correct'], int) and
                0 <= q['correct'] <= 3):
                valid_questions.append(q)
        
        if len(valid_questions) >= num_questions:
            print(f"Debug - Successfully generated {len(valid_questions)} quiz questions")
            return valid_questions[:num_questions]
        else:
            print(f"Debug - Only {len(valid_questions)} valid questions generated, expected {num_questions}")
            # If we don't have enough, fall back to hardcoded
            return None
            
    except Exception as e:
        print(f"Error generating quiz questions: {e}")
        return None


def get_course_recommendations(learning_goal, skill_level, quiz_results, is_regeneration=False):
    """
    Get personalized course recommendations using Gemini API with skill-level adaptation
    
    Args:
        learning_goal: User's selected learning goal
        skill_level: User's skill level (0-100) from quiz
        quiz_results: Quiz result data including performance details
        is_regeneration: Boolean flag to indicate if we should force varied results
    
    Returns:
        List of AI-recommended courses tailored to skill level, with curated fallback
    """
    # Determine skill level descriptor for better AI prompting
    if skill_level < 30:
        level_desc = "complete beginner with no prior experience"
        difficulty = "absolute beginner level, starting from basics"
    elif skill_level < 60:
        level_desc = "beginner with some basic knowledge"
        difficulty = "beginner to early intermediate level"
    elif skill_level < 80:
        level_desc = "intermediate learner with solid fundamentals"
        difficulty = "intermediate level with some advanced topics"
    else:
        level_desc = "advanced learner ready for complex topics"
        difficulty = "advanced level with production-ready skills"
    
    # Goal-specific curated videos - used ONLY as last resort fallback
    curated_videos_by_goal = {
        'Java Developer': [
            {
                'title': 'Java Programming for Beginners',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=grEKMHGYyns',
                'duration': '2:30:00',
                'topics': ['Java', 'Programming', 'OOP']
            },
            {
                'title': 'Java Full Course',
                'platform': 'YouTube',
                'instructor': 'Bro Code',
                'url': 'https://www.youtube.com/watch?v=xk4_1vDrzzo',
                'duration': '12:00:00',
                'topics': ['Java', 'Advanced Java']
            },
            {
                'title': 'Spring Boot Tutorial',
                'platform': 'YouTube',
                'instructor': 'Amigoscode',
                'url': 'https://www.youtube.com/watch?v=9SGDpanrc8U',
                'duration': '3:15:00',
                'topics': ['Spring Boot', 'Java', 'REST API']
            }
        ],
        'Python Developer': [
            {
                'title': 'Python for Beginners - Full Course',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=rfscVS0vtbw',
                'duration': '4:27:32',
                'topics': ['Python', 'Programming']
            },
            {
                'title': 'Python Tutorial - Full Course for Beginners',
                'platform': 'YouTube',
                'instructor': 'Programming with Mosh',
                'url': 'https://www.youtube.com/watch?v=_uQrJ0TkZlc',
                'duration': '6:14:07',
                'topics': ['Python', 'Programming']
            },
            {
                'title': 'Intermediate Python Programming',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=HGOBQPFzWKo',
                'duration': '6:00:00',
                'topics': ['Python', 'Advanced Python']
            }
        ],
        'Web Developer': [
            {
                'title': 'HTML & CSS Full Course',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=mU6anWqZJcc',
                'duration': '11:00:00',
                'topics': ['HTML', 'CSS', 'Web Design']
            },
            {
                'title': 'JavaScript Full Course for Beginners',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=PkZNo7MFNFg',
                'duration': '3:26:43',
                'topics': ['JavaScript', 'Web Development']
            },
            {
                'title': 'React Course for Beginners',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=bMknfKXIFA8',
                'duration': '11:55:27',
                'topics': ['React', 'JavaScript', 'Frontend']
            }
        ],
        'Data Scientist': [
            {
                'title': 'Python for Data Science',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=LHBE6Q9XlzI',
                'duration': '12:00:00',
                'topics': ['Python', 'Data Science', 'Machine Learning']
            },
            {
                'title': 'Machine Learning Course',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=NWONeJKn6kc',
                'duration': '10:00:00',
                'topics': ['Machine Learning', 'AI']
            },
            {
                'title': 'Data Analysis with Python',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=r-uOLxNrNk8',
                'duration': '10:00:00',
                'topics': ['Python', 'Data Analysis', 'Pandas']
            }
        ],
        'Mobile App Developer': [
            {
                'title': 'React Native Tutorial',
                'platform': 'YouTube',
                'instructor': 'Programming with Mosh',
                'url': 'https://www.youtube.com/watch?v=0-S5a0eXPoc',
                'duration': '6:00:00',
                'topics': ['React Native', 'Mobile Development']
            },
            {
                'title': 'Flutter Course for Beginners',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=VPvVD8t02U8',
                'duration': '37:00:00',
                'topics': ['Flutter', 'Dart', 'Mobile Apps']
            },
            {
                'title': 'Android Development Course',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=fis26HvvDII',
                'duration': '11:00:00',
                'topics': ['Android', 'Kotlin', 'Mobile Development']
            }
        ],
        'DevOps Engineer': [
            {
                'title': 'DevOps Engineering Course',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=j5Zsa_eOXeY',
                'duration': '2:15:00',
                'topics': ['DevOps', 'CI/CD', 'Automation']
            },
            {
                'title': 'Docker Tutorial for Beginners',
                'platform': 'YouTube',
                'instructor': 'TechWorld with Nana',
                'url': 'https://www.youtube.com/watch?v=3c-iBn73dDE',
                'duration': '3:10:00',
                'topics': ['Docker', 'Containers', 'DevOps']
            },
            {
                'title': 'Kubernetes Course',
                'platform': 'YouTube',
                'instructor': 'freeCodeCamp.org',
                'url': 'https://www.youtube.com/watch?v=d6WC5n9G_sM',
                'duration': '3:45:00',
                'topics': ['Kubernetes', 'Container Orchestration', 'DevOps']
            }
        ]
    }
    
    # Get goal-specific curated courses, or use general curated courses
    curated_videos = curated_videos_by_goal.get(learning_goal, [
        {
            'title': 'Python for Beginners - Full Course',
            'platform': 'YouTube',
            'instructor': 'freeCodeCamp.org',
            'url': 'https://www.youtube.com/watch?v=rfscVS0vtbw',
            'duration': '4:27:32',
            'topics': ['Python', 'Programming']
        },
        {
            'title': 'JavaScript Full Course for Beginners',
            'platform': 'YouTube',
            'instructor': 'freeCodeCamp.org',
            'url': 'https://www.youtube.com/watch?v=PkZNo7MFNFg',
            'duration': '3:26:43',
            'topics': ['JavaScript', 'Web Development']
        }
    ])
    
    # Get goal-specific curated courses as fallback
    curated_videos = curated_videos_by_goal.get(learning_goal, [
        {
            'title': 'Python for Beginners - Full Course',
            'platform': 'YouTube',
            'instructor': 'freeCodeCamp.org',
            'url': 'https://www.youtube.com/watch?v=rfscVS0vtbw',
            'duration': '4:27:32',
            'topics': ['Python', 'Programming']
        }
    ])
    
    # AI-FIRST APPROACH: Try Gemini with improved skill-level-aware prompt
    print(f"Debug - Requesting AI recommendations for {learning_goal}")
    print(f"Debug - User is {level_desc} (score: {skill_level}/100)")
    
    # Add variety instruction if regenerating
    variety_instruction = ""
    if is_regeneration:
        import random
        seed = random.randint(1, 10000)
        variety_instruction = f"""
    4. **VARIETY & ALTERNATIVES (Regeneration Mode)**:
       - The user has requested NEW recommendations.
       - DO NOT provide the standard/default suggestions.
       - Focus on different aspects, specific frameworks, or project-based tutorials that are different from the usual "Full Course".
       - Random Seed: {seed} (Use this to vary your selection)
       """
    
    # TWO-STEP APPROACH: Ask Gemini for SEARCH TERMS, not video IDs
    # This avoids hallucination - Gemini suggests what to search for, YouTube API finds real videos
    prompt = """You are an expert educational advisor. Recommend YouTube course SEARCH TERMS for this student:

    STUDENT PROFILE:
    - Career Goal: %s
    - Skill Level: %d/100 (%s)
    - Quiz Score: %d%%
    - Assessment Level: %s

    TASK: Generate 3-5 SEARCH QUERIES that will help find the best YouTube courses for this student.

    CRITICAL RULES:
    1. **STRICT RELEVANCE**: The search queries MUST be strictly for the Career Goal: "%s". 
       - DO NOT recommend courses for other languages or frameworks unless they are standard tools for this career.
       - Example: If the goal is "Python Developer", DO NOT suggest JavaScript or Java courses.
    
    2. **Target verified educational channels**:
       - freeCodeCamp.org (primary)
       - Programming with Mosh
       - Traversy Media
       - Bro Code
       - Academind
       - Net Ninja

    3. **Match difficulty to skill level**:
       - Current level: %s
       - Beginner (< 30%%): Search for "full course", "tutorial for beginners", "crash course"
       - Intermediate (30-79%%): Search for "advanced tutorial", "project-based", "complete guide"
       - Advanced (80%%+): Search for "advanced", "best practices", "production-ready"
       
    %s

    RESPONSE FORMAT (JSON only, no markdown):
    [
        {"search_query": "channel_name topic difficulty level", "channel_name": "Channel Name", "difficulty": "beginner/intermediate/advanced", "topics": ["Topic1", "Topic2"]}
    ]

    Return ONLY the JSON array with 3-5 search queries.""" % (
            learning_goal,
            skill_level,
            level_desc,
            quiz_results.get('percentage', 0),
            quiz_results.get('level', 'Beginner'),
            learning_goal,
            difficulty,
            variety_instruction
        )

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean response
        if '```json' in response_text:
            response_text = response_text.split('```json')[1].split('```')[0].strip()
        elif '```' in response_text:
            response_text = response_text.split('```')[1].split('```')[0].strip()
        
        if not response_text.startswith('['):
            start = response_text.find('[')
            end = response_text.rfind(']') + 1
            if start != -1 and end != 0:
                response_text = response_text[start:end]
        
        raw_courses = json.loads(response_text)
        print(f"Debug - Gemini generated {len(raw_courses)} search queries")
        
        # STEP 2: Use Gemini's search queries to find REAL videos via YouTube Search API
        validated_courses = []
        
        for i, search_query_data in enumerate(raw_courses):
            search_query = search_query_data.get('search_query', '').strip()
            channel_hint = search_query_data.get('channel_name', '').strip()
            topics = search_query_data.get('topics', [])
            
            if not search_query:
                print(f"Debug - Search query {i+1}: Missing search_query field")
                continue
            
            print(f"Debug - Searching YouTube for: '{search_query}'")
            
            # Search YouTube for real videos matching this query
            search_results = search_youtube_videos(search_query, max_results=1)  # Get top result
            
            if not search_results:
                print(f"Debug - No results found for: '{search_query}'")
                continue
            
            # Take the first (most relevant) result
            video = search_results[0]
            video_id = video['video_id']
            
            # Verify this video is embeddable
            print(f"Debug - Verifying video {video_id}...")
            video_info = verify_youtube_video_exists(video_id)
            
            if video_info and video_info.get('embeddable'):
                validated_courses.append({
                    'title': video_info.get('title'),
                    'platform': 'YouTube',
                    'instructor': video_info.get('channel'),
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'duration': video_info.get('duration', 'N/A'),
                    'topics': topics
                })
                print(f"Debug - ✓✓ REAL VIDEO FOUND: {video_info.get('title')} by {video_info.get('channel')}")
            else:
                print(f"Debug - ✗ Video {video_id} not embeddable or doesn't exist")
        
        # Use AI courses if we got valid ones, otherwise fall back
        if len(validated_courses) >= 2:  # Accept if we got at least 2 good courses
            print(f"Debug - SUCCESS: Using {len(validated_courses)} AI-recommended courses")
            print(f"Debug - Tailored for {level_desc}")
            return validated_courses[:3]
        else:
            print(f"Debug - Only got {len(validated_courses)} valid courses, using curated fallback")
            return curated_videos[:3]
            
    except json.JSONDecodeError as e:
        print(f"Debug - JSON parse error: {e}")
        print(f"Debug - Falling back to curated courses")
        return curated_videos[:3]
    except Exception as e:
        print(f"Debug - API error: {e}")
        print(f"Debug - Falling back to curated courses")
        return curated_videos[:3]

# Sample data for development/testing
SAMPLE_GOALS = [
    'Java Developer',
    'Python Developer',
    'Web Developer',
    'Data Scientist',
    'Mobile App Developer',
    'DevOps Engineer'
]

SAMPLE_QUIZ_QUESTIONS = {
    'Java Developer': [
        {
            'question': 'What is the main method signature in Java?',
            'options': ['public static void main(String[] args)', 'public void main(String[] args)',
                        'static void main(String[] args)', 'public main(String[] args)'],
            'correct': 0,
            'difficulty': 'easy'
        },
        {
            'question': 'Which keyword is used for inheritance in Java?',
            'options': ['implements', 'extends', 'inherits', 'super'],
            'correct': 1,
            'difficulty': 'easy'
        },
        {
            'question': 'What is encapsulation in Java?',
            'options': ['Hiding implementation details', 'Creating objects', 'Method overloading',
                        'Exception handling'],
            'correct': 0,
            'difficulty': 'medium'
        }
    ],
    'Python Developer': [
        {
            'question': 'Which of the following is used to define a function in Python?',
            'options': ['function', 'def', 'func', 'define'],
            'correct': 1,
            'difficulty': 'easy'
        },
        {
            'question': 'What is the correct way to create a list in Python?',
            'options': ['list = []', 'list = ()', 'list = {}', 'list = <>'],
            'correct': 0,
            'difficulty': 'easy'
        },
        {
            'question': 'Which method is used to add an element to a list?',
            'options': ['add()', 'append()', 'insert()', 'push()'],
            'correct': 1,
            'difficulty': 'medium'
        }
    ],
    'Web Developer': [
        {
            'question': 'What does HTML stand for?',
            'options': ['Hyper Text Markup Language', 'Home Tool Markup Language',
                        'Hyperlinks and Text Markup Language', 'Hyper Text Making Language'],
            'correct': 0,
            'difficulty': 'easy'
        },
        {
            'question': 'Which CSS property is used to change the text color?',
            'options': ['font-color', 'text-color', 'color', 'foreground-color'],
            'correct': 2,
            'difficulty': 'medium'
        },
        {
            'question': 'What is the correct HTML element for the largest heading?',
            'options': ['<h6>', '<h1>', '<heading>', '<header>'],
            'correct': 1,
            'difficulty': 'easy'
        }
    ]
}

# Sample course data (in real implementation, this would come from Gemini API)
SAMPLE_COURSES = {
    'Java Developer': [
        {
            'title': 'Java Programming Masterclass',
            'instructor': 'Tech Academy',
            'duration': '40 hours',
            'modules': [
                'Introduction to Java',
                'Object-Oriented Programming',
                'Data Structures',
                'Exception Handling',
                'Collections Framework',
                'Multithreading',
                'File I/O',
                'JDBC and Database Connectivity'
            ],
            'video_url': 'https://www.youtube.com/watch?v=sample1'
        },
        {
            'title': 'Spring Boot Complete Course',
            'instructor': 'Code Masters',
            'duration': '25 hours',
            'modules': [
                'Spring Boot Basics',
                'REST APIs',
                'Spring Data JPA',
                'Security Implementation',
                'Testing',
                'Deployment'
            ],
            'video_url': 'https://www.youtube.com/watch?v=sample2'
        }
    ],
    'Python Developer': [
        {
            'title': 'Complete Python Bootcamp',
            'instructor': 'Python Pro',
            'duration': '35 hours',
            'modules': [
                'Python Basics',
                'Data Types and Structures',
                'Functions and Modules',
                'Object-Oriented Programming',
                'File Handling',
                'Web Scraping',
                'APIs and Databases',
                'Django Framework'
            ],
            'video_url': 'https://www.youtube.com/watch?v=sample3'
        }
    ],
    'Web Developer': [
        {
            'title': 'Full Stack Web Development',
            'instructor': 'Web Wizards',
            'duration': '50 hours',
            'modules': [
                'HTML5 Fundamentals',
                'CSS3 and Responsive Design',
                'JavaScript ES6+',
                'React.js',
                'Node.js and Express',
                'MongoDB',
                'Authentication & Security',
                'Deployment and DevOps'
            ],
            'video_url': 'https://www.youtube.com/watch?v=sample4'
        }
    ]
}


def hash_password(password):
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())


def check_password(password, hashed):
    """Check password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed)


def login_required(f):
    """Decorator to require login"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator to require admin access"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        if not user or not user.get('is_admin', False):
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)

    return decorated_function


@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        # Check if user already exists
        if mongo.db.users.find_one({'email': email}):
            flash('Email already registered!', 'error')
            return redirect(url_for('register'))

        # Create new user
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
        return redirect(url_for('onboarding'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = mongo.db.users.find_one({'email': email})

        if user and check_password(password, user['password']):
            session['user_id'] = str(user['_id'])
            session['is_admin'] = bool(user.get('is_admin', False))
            flash('Login successful!', 'success')

            # Redirect admin to admin panel
            if user.get('is_admin', False):
                return redirect(url_for('admin_dashboard'))

            # Redirect to onboarding if no learning goal set
            if not user.get('learning_goal'):
                return redirect(url_for('onboarding'))

            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password!', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """User logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    """User onboarding - select learning goal"""
    if request.method == 'POST':
        learning_goal = request.form['learning_goal']

        # Update user's learning goal
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$set': {'learning_goal': learning_goal}}
        )

        flash(f'Learning goal set: {learning_goal}', 'success')
        return redirect(url_for('assessment'))

    return render_template('onboarding.html', goals=SAMPLE_GOALS)


@app.route('/assessment', methods=['GET', 'POST'])
@login_required
def assessment():
    """Skill assessment quiz with dynamically generated questions"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    learning_goal = user.get('learning_goal')

    if not learning_goal:
        return redirect(url_for('onboarding'))

    if request.method == 'POST':
        # Retrieve questions from session (generated on GET)
        questions = session.get('current_quiz_questions', [])
        
        if not questions:
            flash('Quiz session expired. Please try again.', 'error')
            return redirect(url_for('assessment'))
        
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
            
            # Store detailed result for each question
            detailed_results.append({
                'question': question['question'],
                'options': question['options'],
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'is_correct': is_correct,
                'difficulty': question.get('difficulty', 'medium')
            })

        # Calculate percentage and level
        percentage = (score / len(questions)) * 100 if questions else 0

        if percentage >= 80:
            level = 'Advanced'
        elif percentage >= 60:
            level = 'Intermediate'
        else:
            level = 'Beginner'

        # Save quiz result with detailed answers
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

        # Save test results to local file
        save_test_results_to_file(user, quiz_result)

        # Clear quiz questions from session
        session.pop('current_quiz_questions', None)
        session['quiz_result'] = quiz_result
        return redirect(url_for('assessment_results'))

    # GET request - generate new questions
    print(f"Debug - Generating quiz questions for {learning_goal}")
    
    # Try to generate questions using Gemini
    questions = generate_quiz_questions(learning_goal, num_questions=10)
    
    # Fallback to hardcoded questions if generation fails
    if not questions:
        print("Debug - Falling back to hardcoded questions")
        questions = SAMPLE_QUIZ_QUESTIONS.get(learning_goal, [])
        
        # If no hardcoded questions exist for this goal, create generic ones
        if not questions:
            flash('No questions available for this learning goal. Please select a different goal.', 'error')
            return redirect(url_for('onboarding'))
    
    # Store questions in session for POST validation
    session['current_quiz_questions'] = questions
    
    return render_template('assessment.html', questions=questions, learning_goal=learning_goal)


@app.route('/regenerate-recommendations')
@login_required
def regenerate_recommendations():
    """Regenerate recommendations using the last assessment result"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    quiz_history = user.get('quiz_history', [])
    
    last_result = None
    
    if quiz_history:
        last_result = quiz_history[-1]
    else:
        # Try to get from file
        last_result = get_latest_assessment_from_file(user.get('email'))
        
    if not last_result:
        flash('No previous assessment found. Please take the assessment first.', 'warning')
        return redirect(url_for('assessment'))
    
    # Store in session for assessment_results to pick up
    session['quiz_result'] = last_result
    session['is_regeneration'] = True  # Flag to trigger varied recommendations
    
    # Clear existing recommendations to force refresh
    session.pop('recommended_courses', None)
    
    flash('Generating fresh recommendations based on your previous assessment...', 'info')
    return redirect(url_for('assessment_results'))


@app.route('/assessment-results')
@login_required
def assessment_results():
    """Display assessment results and personalized course recommendations"""
    quiz_result = session.pop('quiz_result', None)
    if not quiz_result:
        return redirect(url_for('dashboard'))

    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    learning_goal = user.get('learning_goal')
    skill_level = user.get('skill_level', 0)
    is_regeneration = session.pop('is_regeneration', False)

    # Get personalized course recommendations from Gemini
    recommended_courses = get_course_recommendations(
        learning_goal=learning_goal,
        skill_level=skill_level,
        quiz_results=quiz_result,
        is_regeneration=is_regeneration
    )
    
    # Store recommendations in session for add_course route
    session['recommended_courses'] = recommended_courses
    
    # Get bookmarked course URLs for checking
    bookmarked_urls = [b.get('url') for b in user.get('bookmarked_courses', [])]

    return render_template('assessment_results.html',
                           quiz_result=quiz_result,
                           recommended_courses=recommended_courses,
                           learning_goal=learning_goal,
                           bookmarked_urls=bookmarked_urls)


@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard - shows only ongoing courses"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

    # Calculate statistics
    all_courses = user.get('courses', [])
    total_courses = len(all_courses)
    completed_courses = len([c for c in all_courses if c.get('completed', False)])
    certificates_earned = len(user.get('certificates', []))

    # Get quiz history for chart
    quiz_history = user.get('quiz_history') or []
    print(f"Debug - Dashboard: User {user.get('email')}")
    print(f"Debug - Dashboard: quiz_history type: {type(quiz_history)}")
    print(f"Debug - Dashboard: quiz_history length: {len(quiz_history) if isinstance(quiz_history, list) else 'N/A'}")
    
    # Check if user has any assessment history (DB or file)
    has_assessment_history = bool(quiz_history)

    # FORCE CHECK for file-based assessment regardless of quiz_history
    # This ensures we catch cases where quiz_history might be empty but files exist
    user_email = user.get('email', '').strip()
    if user_email:
        latest_file_result = get_latest_assessment_from_file(user_email)
        if latest_file_result:
            has_assessment_history = True

    # Filter to show ONLY ongoing (not completed) courses on dashboard
    # Store original indices with each course for proper routing
    ongoing_courses = []
    for i, course in enumerate(all_courses):
        if not course.get('completed', False):
            course_with_index = course.copy()
            course_with_index['original_index'] = i
            ongoing_courses.append(course_with_index)
    
    # Get recommended courses from session (courses that haven't been enrolled yet)
    recommended_courses = session.get('recommended_courses', [])
    
    # Filter out courses that are already enrolled
    enrolled_course_titles = {course.get('title') for course in all_courses}
    available_recommended_courses = [
        course for course in recommended_courses 
        if course.get('title') not in enrolled_course_titles
    ]
    
    # Count recommendations
    recommendations_count = len(available_recommended_courses)
    
    # Get bookmarked course URLs for checking if recommended courses are bookmarked
    bookmarked_urls = [b.get('url') for b in user.get('bookmarked_courses', [])]

    return render_template('dashboard.html',
                           user=user,
                           total_courses=total_courses,
                           completed_courses=completed_courses,
                           certificates_earned=certificates_earned,
                           quiz_history=quiz_history,
                           has_assessment_history=has_assessment_history,
                           courses=ongoing_courses,  # Only ongoing courses with original indices
                           recommended_courses=available_recommended_courses,
                           recommendations_count=recommendations_count,
                           bookmarked_urls=bookmarked_urls)


@app.route('/my-courses')
@login_required
def my_courses():
    """My Courses page - shows all courses with tabs for filtering"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

    # Get all courses
    courses = user.get('courses', [])
    
    # Calculate statistics
    total_courses = len(courses)
    completed_courses = len([c for c in courses if c.get('completed', False)])
    ongoing_courses = total_courses - completed_courses
    
    # Get bookmarked courses
    bookmarked_courses = user.get('bookmarked_courses', [])
    
    # Check if user has any assessment history (DB or file)
    quiz_history = user.get('quiz_history', [])
    has_assessment_history = bool(quiz_history)
    if not has_assessment_history:
        # Check for file-based assessment
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


@app.route('/add-course/<int:course_index>')
@login_required
def add_course(course_index):
    """Add a course to user's learning path"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    recommended_courses = session.get('recommended_courses', [])

    if course_index < len(recommended_courses):
        course = recommended_courses[course_index].copy()
        # Add additional course tracking fields
        course['enrolled_date'] = datetime.datetime.now()
        course['completed'] = False
        course['completion_percentage'] = 0
        course['videos_progress'] = {
            video['url']: {
                'title': video['title'],
                'watched': False,
                'watch_time': 0,  # Store time in seconds
                'last_position': 0,  # Store last video position
                'completed': False
            } for video in course.get('videos', [])
        }
        
        # Add course to user's courses
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$push': {'courses': course}}
        )

        flash(f'Course "{course["title"]}" added to your learning path!', 'success')
    else:
        flash('Course not found!', 'error')

    return redirect(url_for('dashboard'))


@app.route('/course/<int:course_index>')
@login_required
def view_course(course_index):
    """View enrolled course details and track progress"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    
    print(f"Debug - view_course called with course_index: {course_index}")
    
    # Only handle enrolled courses - no auto-enrollment logic here
    courses = user.get('courses', [])
    print(f"Debug - User has {len(courses)} enrolled courses")
    
    if course_index < len(courses):
        course = courses[course_index]
        print(f"Debug - Loading enrolled course: {course['title']}")
        return render_template('course.html', 
                            course=course, 
                            course_index=course_index,
                            videos_progress=course.get('videos_progress', {}),
                            is_enrolled=True)
    
    print(f"Debug - Course index {course_index} not found in enrolled courses")
    flash('Course not found!', 'error')
    return redirect(url_for('dashboard'))

@app.route('/course/recommended/<int:course_index>')
@login_required
def view_course_recommended(course_index):
    """View recommended course - auto-enroll and view without redirects"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    recommended_courses = session.get('recommended_courses', [])
    
    print(f"Debug - view_course_recommended called with course_index: {course_index}")
    print(f"Debug - Number of recommended courses in session: {len(recommended_courses)}")
    
    if not recommended_courses or course_index >= len(recommended_courses):
        flash('Recommended course not found!', 'error')
        return redirect(url_for('dashboard'))
    
    course = recommended_courses[course_index].copy()
    print(f"Debug - Processing recommended course: {course['title']}")
    
    # Check if this course is already enrolled (to avoid duplicates)
    user_courses = user.get('courses', [])
    course_already_enrolled = False
    enrolled_course_index = -1
    
    for i, enrolled_course in enumerate(user_courses):
        if enrolled_course.get('title') == course['title'] and enrolled_course.get('url') == course.get('url'):
            course_already_enrolled = True
            enrolled_course_index = i
            print(f"Debug - Course already enrolled at index {i}")
            break
    
    if course_already_enrolled:
        # If already enrolled, view the enrolled course directly without redirect
        enrolled_course = user_courses[enrolled_course_index]
        print(f"Debug - Viewing already enrolled course")
        return render_template('course.html', 
                            course=enrolled_course, 
                            course_index=enrolled_course_index,
                            videos_progress=enrolled_course.get('videos_progress', {}),
                            is_enrolled=True)
    
    # Auto-enroll the course
    print("Debug - Auto-enrolling user in recommended course")
    
    # Transform the course to include video information
    if isinstance(course.get('url'), str):
        video_url = course['url']
        print(f"Debug - Original video URL from course data: {video_url}")
        
        # Ensure we have a proper video URL
        if not video_url or '?embeds_referring' in video_url or not ('youtube.com/watch?v=' in video_url or 'youtu.be/' in video_url):
            print("Debug - Invalid URL format detected, using default video")
            video_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
            print(f"Debug - Using fallback URL: {video_url}")
        
        # Extract video ID and rebuild URL to ensure correct format
        try:
            if 'youtube.com' in video_url:
                video_id = video_url.split('v=')[1].split('&')[0]
                print(f"Debug - Extracted video ID from youtube.com URL: {video_id}")
            elif 'youtu.be' in video_url:
                video_id = video_url.split('/')[-1].split('?')[0]
                print(f"Debug - Extracted video ID from youtu.be URL: {video_id}")
            else:
                video_id = None
                print("Debug - Could not extract video ID from URL format")
                
            if video_id and len(video_id) == 11:
                video_url = f'https://www.youtube.com/watch?v={video_id}'
                print(f"Debug - Normalized video URL: {video_url}")
            else:
                print(f"Debug - Invalid video ID: {video_id}")
                video_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
                print(f"Debug - Using fallback URL: {video_url}")
        except Exception as e:
            print(f"Debug - Error processing URL: {e}")
            video_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
            print(f"Debug - Using fallback URL due to error: {video_url}")
        
        course['videos'] = [{
            'title': course['title'],
            'url': video_url,
            'duration': course.get('duration', ''),
        }]
    
    # Add enrollment tracking fields
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
    
    # Add course to user's enrolled courses
    mongo.db.users.update_one(
        {'_id': ObjectId(session['user_id'])},
        {'$push': {'courses': course}}
    )
    
    # Get the new course index
    updated_user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    new_course_index = len(updated_user.get('courses', [])) - 1
    
    print(f"Debug - New enrolled course index: {new_course_index}")
    
    # Show success message and render course directly (no redirect)
    flash(f'Course "{course["title"]}" has been added to your learning path!', 'success')
    
    return render_template('course.html', 
                        course=course, 
                        course_index=new_course_index,
                        videos_progress=course.get('videos_progress', {}),
                        is_enrolled=True)

@app.route('/api/dismiss-recommendation', methods=['POST'])
@login_required
def dismiss_recommendation():
    """Remove a course from the recommended courses list"""
    try:
        data = request.get_json()
        course_index = data.get('course_index')
        
        if course_index is None:
            return jsonify({'success': False, 'error': 'Course index required'})
        
        # Get current recommended courses
        recommended_courses = session.get('recommended_courses', [])
        
        if course_index < 0 or course_index >= len(recommended_courses):
            return jsonify({'success': False, 'error': 'Invalid course index'})
        
        # Remove the course at the specified index
        removed_course = recommended_courses.pop(course_index)
        session['recommended_courses'] = recommended_courses
        session.modified = True
        
        print(f"Debug - Dismissed recommendation: {removed_course.get('title', 'Unknown')}")
        
        return jsonify({'success': True, 'message': 'Recommendation dismissed'})
        
    except Exception as e:
        print(f"Error dismissing recommendation: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/remove-course', methods=['POST'])
@login_required
def remove_course():
    """Remove a course from user's enrolled courses"""
    try:
        data = request.get_json()
        course_index = data.get('course_index')
        
        if course_index is None:
            return jsonify({'success': False, 'error': 'Course index required'})
        
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        courses = user.get('courses', [])
        
        if course_index < 0 or course_index >= len(courses):
            return jsonify({'success': False, 'error': 'Invalid course index'})
        
        # Get the course being removed for logging
        removed_course = courses[course_index]
        course_title = removed_course.get('title', 'Unknown')
        
        # Remove the course from the user's courses array
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$pull': {'courses': removed_course}}
        )
        
        print(f"Debug - Removed course: {course_title} (index {course_index}) for user {session['user_id']}")
        
        return jsonify({
            'success': True, 
            'message': f'Course "{course_title}" removed successfully'
        })
        
    except Exception as e:
        print(f"Error removing course: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/debug/session')
@login_required
def debug_session():
    """Debug route to check session data"""
    if not app.debug:
        return "Debug mode only", 403
    
    session_data = {
        'recommended_courses_count': len(session.get('recommended_courses', [])),
        'recommended_courses': session.get('recommended_courses', []),
        'session_keys': list(session.keys())
    }
    
    return jsonify(session_data)

@app.route('/update-video-progress', methods=['POST'])
@login_required
def update_video_progress():
    """Update video progress for both recommended and enrolled courses"""
    try:
        course_index = int(request.form.get('course_index'))
        raw_video_url = request.form.get('video_url')
        video_url = canonical_youtube_url(raw_video_url) or raw_video_url
        current_time = float(request.form.get('current_time', 0))
        duration = float(request.form.get('duration', 0))
        is_completed = request.form.get('completed') == 'true'

        print(f"Debug - Progress update request:")
        print(f"  - Course index: {course_index}")
        print(f"  - Video URL: {video_url}")
        print(f"  - Current time: {current_time}")
        print(f"  - Duration: {duration}")
        print(f"  - Completed: {is_completed}")

        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        # IMPORTANT: Always prioritize enrolled courses (database) first
        # because recommended courses may still be present in session and
        # using the index alone can misroute updates to the session branch.
        courses = user.get('courses', [])
        if course_index < len(courses):
            print("Debug - Updating progress for enrolled course (database)")
            course = courses[course_index]
            
            # Initialize videos_progress if it doesn't exist
            if 'videos_progress' not in course:
                course['videos_progress'] = {}
            
            if video_url not in course['videos_progress']:
                course['videos_progress'][video_url] = {
                    'watch_time': 0,
                    'last_position': 0,
                    'completed': False
                }
            
            # Determine if video is completed (1 second before end or explicitly marked)
            video_is_completed = is_completed or (duration > 0 and current_time >= (duration - 1))
            
            # Update video progress
            course['videos_progress'][video_url].update({
                'watch_time': current_time,
                'last_position': current_time,
                'completed': video_is_completed
            })

            # Calculate overall course progress based on TIME WATCHED, not just video count
            declared_urls = []
            for v in course.get('videos', []):
                url = canonical_youtube_url(v.get('url') or '')
                if url:
                    declared_urls.append(url)

            if declared_urls:
                # Ensure progress dict has entries for declared videos only
                filtered_progress = {}
                for url in declared_urls:
                    if url in course['videos_progress']:
                        filtered_progress[url] = course['videos_progress'][url]
                    else:
                        filtered_progress[url] = {'watch_time': 0, 'last_position': 0, 'completed': False}
                course['videos_progress'] = filtered_progress
                
                # NEW: Duration-based progress calculation
                # Get total duration of all videos (if available)
                total_videos = len(declared_urls)
                
                if total_videos == 1:
                    # Single video course - calculate based on watch time
                    if duration > 0:
                        # Progress in 12.5% increments
                        raw_progress = (current_time / duration) * 100
                        # Round to nearest 12.5% increment
                        progress_percentage = round(raw_progress / 12.5) * 12.5
                        # Ensure we don't exceed 100% until video is actually done
                        if current_time < (duration - 1):
                            progress_percentage = min(progress_percentage, 87.5)  # Max 87.5% until last second
                        else:
                            progress_percentage = 100  # Mark complete at last second
                        course['completion_percentage'] = progress_percentage
                    else:
                        course['completion_percentage'] = 0
                else:
                    # Multiple videos - calculate based on completed count
                    completed_videos = len([v for v in course['videos_progress'].values() if v['completed']])
                    course['completion_percentage'] = (completed_videos / total_videos) * 100
            else:
                # Fallback to old method if no declared videos
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
            
            print(f"Debug - Course progress: {course['completion_percentage']}% (current: {current_time}s / duration: {duration}s)")

            # Check if course is completed
            if course['completion_percentage'] >= 100 and not course.get('completed'):
                course['completed'] = True
                course['completion_date'] = datetime.datetime.now()

                # Get user for learning goal
                user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

                # Generate certificate
                certificate_code = generate_unique_certificate_id()
                certificate = {
                    'certificate_id': certificate_code,
                    'certificate_code': certificate_code,  # Keep for backward compatibility
                    'course_title': course['title'],
                    'instructor': course.get('instructor', 'Expert Instructor'),
                    'completion_date': datetime.datetime.now(),
                    'issued_date': datetime.datetime.now(),
                    'learning_goal': user.get('learning_goal', 'General Learning')
                }

                # Update user with completed course and certificate
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

            # Update course progress in database
            mongo.db.users.update_one(
                {'_id': ObjectId(session['user_id'])},
                {'$set': {f'courses.{course_index}': course}}
            )

            return jsonify({
                'status': 'success',
                'progress': course['completion_percentage']
            })

        # If not an enrolled course, check if this is a recommended course (session-based)
        recommended_courses = session.get('recommended_courses', [])
        if recommended_courses and course_index < len(recommended_courses):
            print("Debug - Updating progress for recommended course (session-based)")
            
            # For recommended courses, we'll store progress in the session
            if 'course_progress' not in session:
                session['course_progress'] = {}
            
            course_key = f"course_{course_index}"
            if course_key not in session['course_progress']:
                session['course_progress'][course_key] = {'videos_progress': {}}
            
            # Update video progress in session
            if video_url not in session['course_progress'][course_key]['videos_progress']:
                session['course_progress'][course_key]['videos_progress'][video_url] = {
                    'watch_time': 0,
                    'last_position': 0,
                    'completed': False
                }
            
            # Calculate if video should be marked as completed (1 second before end)
            is_video_completed = is_completed or (duration > 0 and current_time >= (duration - 1))
            
            session['course_progress'][course_key]['videos_progress'][video_url].update({
                'watch_time': current_time,
                'last_position': current_time,
                'completed': is_video_completed
            })
            
            # Calculate progress for recommended course in 12.5% increments
            if duration > 0 and duration != float('inf') and math.isfinite(duration):
                # Calculate raw progress
                raw_progress = (current_time / duration) * 100
                
                # Round to nearest 12.5% increment (0, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100)
                progress_percentage = round(raw_progress / 12.5) * 12.5
                
                # Don't mark as 100% until the last second
                if current_time < (duration - 1):
                    progress_percentage = min(progress_percentage, 87.5)
                else:
                    progress_percentage = 100.0
            else:
                print(f"Debug - Invalid duration detected: {duration}")
                progress_percentage = 0
            
            # Ensure progress is within bounds
            progress_percentage = max(0, min(100, progress_percentage))
            
            print(f"Debug - Video progress calculation (recommended):")
            print(f"  - Current time: {current_time} seconds")
            print(f"  - Total duration: {duration} seconds")
            print(f"  - Raw progress: {(current_time / duration * 100) if duration > 0 else 0:.2f}%")
            print(f"  - Rounded progress (12.5% increments): {progress_percentage}%")
            print(f"  - Video completed: {is_video_completed}")
            
            return jsonify({
                'status': 'success',
                'progress': progress_percentage,
                'completed': is_video_completed and progress_percentage >= 100
            })

        print("Debug - Course not found in recommended or enrolled courses")
        return jsonify({'status': 'error', 'message': 'Course not found'}), 400

    except Exception as e:
        print(f"Debug - Error in update_video_progress: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400


@app.route('/update-progress/<int:course_index>/<int:module_index>')
@login_required
def update_progress(course_index, module_index):
    """Update module completion progress"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    courses = user.get('courses', [])

    if course_index < len(courses):
        course = courses[course_index]
        modules = course['modules']

        if module_index < len(modules):
            module_name = modules[module_index]

            # Toggle module completion
            course['progress'][module_name] = not course['progress'].get(module_name, False)

            # Calculate completion percentage
            completed_modules = sum(1 for completed in course['progress'].values() if completed)
            course['completion_percentage'] = (completed_modules / len(modules)) * 100

            # Check if course is completed
            if course['completion_percentage'] == 100 and not course.get('completed'):
                course['completed'] = True
                course['completion_date'] = datetime.datetime.now()

                # Get user for learning goal
                user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

                # Generate certificate
                certificate_code = generate_unique_certificate_id()
                certificate = {
                    'certificate_id': certificate_code,
                    'certificate_code': certificate_code,  # Keep for backward compatibility
                    'course_title': course['title'],
                    'instructor': course.get('instructor', 'Expert Instructor'),
                    'completion_date': datetime.datetime.now(),
                    'issued_date': datetime.datetime.now(),
                    'learning_goal': user.get('learning_goal', 'General Learning')
                }

                # Update user with completed course and certificate
                mongo.db.users.update_one(
                    {'_id': ObjectId(session['user_id'])},
                    {
                        '$set': {f'courses.{course_index}': course},
                        '$push': {'certificates': certificate}
                    }
                )

                flash(f'Congratulations! You completed "{course["title"]}" and earned a certificate!', 'success')
            else:
                # Update course progress
                mongo.db.users.update_one(
                    {'_id': ObjectId(session['user_id'])},
                    {'$set': {f'courses.{course_index}': course}}
                )

                flash(f'Progress updated for "{module_name}"!', 'success')

    return redirect(url_for('view_course', course_index=course_index))


@app.route('/bookmark-course', methods=['POST'])
@login_required
def bookmark_course():
    """Add a course to user's bookmarks"""
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
        
        # Check if already bookmarked
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        bookmarks = user.get('bookmarked_courses', [])
        
        # Check if course already bookmarked (by URL)
        if any(b.get('url') == course_data['url'] for b in bookmarks):
            return jsonify({'status': 'error', 'message': 'Course already bookmarked'})
        
        # Add to bookmarks
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$push': {'bookmarked_courses': course_data}}
        )
        
        return jsonify({'status': 'success', 'message': 'Course bookmarked successfully'})
    except Exception as e:
        print(f"Error bookmarking course: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/remove-bookmark', methods=['POST'])
@login_required
def remove_bookmark():
    """Remove a course from user's bookmarks"""
    try:
        data = request.get_json()
        course_url = data.get('url')
        
        if not course_url:
            return jsonify({'status': 'error', 'message': 'Course URL required'})
        
        # Remove bookmark by URL
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$pull': {'bookmarked_courses': {'url': course_url}}}
        )
        
        return jsonify({'status': 'success', 'message': 'Bookmark removed successfully'})
    except Exception as e:
        print(f"Error removing bookmark: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/enroll-from-bookmark', methods=['POST'])
@login_required
def enroll_from_bookmark():
    """Enroll in a bookmarked course"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['title', 'url']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'status': 'error', 'message': f'Missing required field: {field}'}), 400
        
        user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        courses = user.get('courses', [])
        
        # Check if already enrolled
        for i, course in enumerate(courses):
            if course.get('url') == data['url']:
                print(f"Debug - Course already enrolled at index {i}")
                return jsonify({'status': 'success', 'course_index': i, 'already_enrolled': True})
        
        # Create course object for enrollment
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
        
        # Transform URL to videos array
        if course.get('url'):
            video_url = course['url']
            course['videos'] = [{
                'title': course['title'],
                'url': video_url,
                'duration': course.get('duration', ''),
            }]
        
        # Initialize video progress tracking
        course['videos_progress'] = {
            video['url']: {
                'title': video['title'],
                'watched': False,
                'watch_time': 0,
                'last_position': 0,
                'completed': False
            } for video in course.get('videos', [])
        }
        
        # Add course to user's enrolled courses
        mongo.db.users.update_one(
            {'_id': ObjectId(session['user_id'])},
            {'$push': {'courses': course}}
        )
        
        # Get the new course index
        updated_user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
        new_course_index = len(updated_user.get('courses', [])) - 1
        
        print(f"Debug - Enrolled in bookmarked course: {course['title']} at index {new_course_index}")
        
        return jsonify({
            'status': 'success', 
            'course_index': new_course_index,
            'message': f'Enrolled in {course["title"]}'
        })
        
    except Exception as e:
        print(f"Error enrolling from bookmark: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/certificates')
@login_required
def certificates():
    """View user certificates"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    certificates = user.get('certificates', [])

    return render_template('certificates.html', certificates=certificates)


@app.route('/test-results')
@login_required
def test_results():
    """View past test results"""
    import os
    
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    
    # Get test results from database (quiz_history)
    quiz_history = user.get('quiz_history', [])
    
    # Convert datetime objects to ISO format strings for JavaScript
    quiz_history_formatted = []
    for quiz in quiz_history:
        quiz_copy = quiz.copy()
        if quiz_copy.get('date'):
            # Convert datetime to ISO format string
            quiz_copy['date'] = quiz_copy['date'].isoformat()
        quiz_history_formatted.append(quiz_copy)
    
    # Also check for files in Test Results folder
    results_dir = os.path.join(os.getcwd(), 'Test Results')
    file_results = []
    
    if os.path.exists(results_dir):
        files = [f for f in os.listdir(results_dir) if f.endswith('.txt')]
        for filename in sorted(files, reverse=True):  # Most recent first
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


@app.route('/view-test-result/<path:filename>')
@login_required
def view_test_result(filename):
    """View a specific test result file"""
    import os
    
    results_dir = os.path.join(os.getcwd(), 'Test Results')
    filepath = os.path.join(results_dir, filename)
    
    # Security check - ensure file is in Test Results directory
    if not filepath.startswith(results_dir):
        flash('Invalid file path!', 'error')
        return redirect(url_for('test_results'))
    
    if not os.path.exists(filepath):
        flash('Test result file not found!', 'error')
        return redirect(url_for('test_results'))
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return render_template('view_test_result.html', 
                             filename=filename, 
                             content=content)
    except Exception as e:
        flash(f'Error reading file: {str(e)}', 'error')
        return redirect(url_for('test_results'))


@app.route('/download-certificate/<certificate_code>')
@login_required
def download_certificate(certificate_code):
    """Download certificate as PDF"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})
    certificates = user.get('certificates', [])

    # Find certificate by certificate_code OR certificate_id (for backward compatibility)
    certificate = next(
        (cert for cert in certificates 
         if cert.get('certificate_code') == certificate_code 
         or cert.get('certificate_id') == certificate_code), 
        None
    )

    if not certificate:
        flash('Certificate not found!', 'error')
        return redirect(url_for('certificates'))

    # Find the corresponding course to get instructor information
    course_title = certificate['course_title']
    courses = user.get('courses', [])
    corresponding_course = next((c for c in courses if c.get('title') == course_title), None)
    
    # Get instructor name (fallback to certificate data or default)
    if corresponding_course and corresponding_course.get('instructor'):
        instructor_name = corresponding_course['instructor']
    elif certificate.get('instructor'):
        instructor_name = certificate['instructor']
    else:
        instructor_name = 'Expert Instructor'
    
    # Get course URL for creating channel link
    course_url = None
    if corresponding_course and corresponding_course.get('url'):
        course_url = corresponding_course['url']

    # Create PDF certificate
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    # Certificate design
    width, height = letter  # 612 x 792 points

    # Helper function for centered text
    def draw_centered_text(canvas_obj, y_pos, text, font_name, font_size, color=None):
        """Draw text centered horizontally on the page"""
        if color:
            canvas_obj.setFillColor(color)
        canvas_obj.setFont(font_name, font_size)
        text_width = canvas_obj.stringWidth(text, font_name, font_size)
        x_pos = (width - text_width) / 2
        canvas_obj.drawString(x_pos, y_pos, text)

    # Outer border
    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(4)
    p.rect(40, 40, width - 80, height - 80)

    # Inner decorative border
    p.setStrokeColor(Color(0.8, 0.8, 0.8))
    p.setLineWidth(1)
    p.rect(55, 55, width - 110, height - 110)

    # Title - "CERTIFICATE OF COMPLETION"
    draw_centered_text(p, height - 120, "CERTIFICATE OF COMPLETION", 
                      "Helvetica-Bold", 32, Color(0.2, 0.4, 0.8))

    # Decorative line under title
    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(2)
    line_y = height - 135
    p.line(width / 2 - 180, line_y, width / 2 + 180, line_y)

    # "This is to certify that"
    draw_centered_text(p, height - 200, "This is to certify that", 
                      "Helvetica", 16, Color(0.3, 0.3, 0.3))

    # User name (prominent)
    user_name = user['name'].upper()
    draw_centered_text(p, height - 260, user_name, 
                      "Helvetica-Bold", 28, Color(0.1, 0.1, 0.1))

    # Decorative line under name
    p.setStrokeColor(Color(0.7, 0.7, 0.7))
    p.setLineWidth(1)
    p.setFont("Helvetica-Bold", 28)
    name_width = p.stringWidth(user_name, "Helvetica-Bold", 28)
    name_line_y = height - 275
    p.line(width / 2 - name_width / 2 - 15, name_line_y, 
           width / 2 + name_width / 2 + 15, name_line_y)

    # "has successfully completed the course"
    draw_centered_text(p, height - 320, "has successfully completed the course", 
                      "Helvetica", 16, Color(0.3, 0.3, 0.3))

    # Course title (with dynamic sizing and intelligent line wrapping)
    course_title = certificate['course_title']
    
    # Calculate optimal font size and wrapping based on title length
    title_length = len(course_title)
    
    if title_length <= 40:
        # Short title - use larger font, single line
        title_font_size = 20
        title_lines = [course_title]
        base_y = height - 370
    elif title_length <= 70:
        # Medium title - normal font, possibly 2 lines
        title_font_size = 18
        # Smart word wrap - check if it fits in one line first
        p.setFont("Helvetica-Bold", title_font_size)
        if p.stringWidth(course_title, "Helvetica-Bold", title_font_size) <= (width - 120):
            title_lines = [course_title]
        else:
            # Wrap to 2 lines
            words = course_title.split()
            lines = []
            current_line = ""
            for word in words:
                test_line = current_line + (" " + word if current_line else word)
                if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 120):
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)
            title_lines = lines[:2]  # Max 2 lines
        base_y = height - 370
    else:
        # Long title - smaller font, up to 3 lines
        title_font_size = 16
        words = course_title.split()
        lines = []
        current_line = ""
        p.setFont("Helvetica-Bold", title_font_size)
        for word in words:
            test_line = current_line + (" " + word if current_line else word)
            if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 100):
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        title_lines = lines[:3]  # Max 3 lines
        base_y = height - 360  # Start slightly higher for more lines
    
    # Draw the course title lines
    line_spacing = title_font_size + 5  # Dynamic line spacing based on font size
    for i, line in enumerate(title_lines):
        y_position = base_y - (i * line_spacing)
        draw_centered_text(p, y_position, f'"{line}"' if i == 0 else line, 
                         "Helvetica-Bold", title_font_size, Color(0.2, 0.4, 0.8))
    
    # Calculate dynamic Y position for instructor based on number of title lines
    num_title_lines = len(title_lines)
    instructor_y = base_y - (num_title_lines * line_spacing) - 20  # 20pt gap after title

    # Instructor/Channel name (giving credit) with clickable link
    instructor_text = f"by {instructor_name}"
    p.setFillColor(Color(0.3, 0.3, 0.3))
    p.setFont("Helvetica-Oblique", 13)
    text_width = p.stringWidth(instructor_text, "Helvetica-Oblique", 13)
    x_pos = (width - text_width) / 2
    
    # Draw the text at dynamic position
    p.drawString(x_pos, instructor_y, instructor_text)
    
    # Add clickable link annotation if course URL exists
    if course_url:
        # Create a link annotation (clickable area)
        # Extract channel URL from video URL
        if 'youtube.com' in course_url or 'youtu.be' in course_url:
            # Try to extract channel URL
            # For now, link to the video itself as it shows the channel
            link_rect = (x_pos, instructor_y - 2, x_pos + text_width, instructor_y + 13)
            p.linkURL(course_url, link_rect, relative=0)
            
            # Underline to indicate it's a link
            p.setStrokeColor(Color(0.3, 0.3, 0.3))
            p.setLineWidth(0.5)
            p.line(x_pos, instructor_y - 1, x_pos + text_width, instructor_y - 1)

    # Calculate dynamic positions for date and certificate ID
    date_y = instructor_y - 45  # 45pt gap after instructor
    cert_id_y = date_y - 25  # 25pt gap after date

    # Completion date
    completion_date = certificate['completion_date'].strftime("%B %d, %Y")
    draw_centered_text(p, date_y, f"Completed on: {completion_date}", 
                      "Helvetica", 14, Color(0.4, 0.4, 0.4))

    # Certificate ID
    draw_centered_text(p, cert_id_y, f"Certificate ID: {certificate['certificate_code']}", 
                      "Helvetica", 12, Color(0.5, 0.5, 0.5))

    # Decorative elements (circles on sides) - positioned dynamically in middle
    circle_y = (height - 120 + cert_id_y) / 2  # Midpoint between title and bottom content
    # Left decoration
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(100, circle_y, 18, fill=1)

    # Right decoration
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(width - 100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(width - 100, circle_y, 18, fill=1)

    # Platform name and tagline at bottom
    draw_centered_text(p, 140, "Personalized Education Platform", 
                      "Helvetica-Bold", 13, Color(0.5, 0.5, 0.5))
    draw_centered_text(p, 120, "Empowering Learners Worldwide", 
                      "Helvetica-Oblique", 11, Color(0.6, 0.6, 0.6))

    # Timestamp for authenticity (small, bottom left)
    p.setFillColor(Color(0.7, 0.7, 0.7))
    p.setFont("Helvetica", 7)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    p.drawString(50, 50, f"Generated: {timestamp}")

    # Signature line (optional decorative element)
    p.setStrokeColor(Color(0.5, 0.5, 0.5))
    p.setLineWidth(1)
    sig_y = 220
    p.line(width / 2 - 100, sig_y, width / 2 + 100, sig_y)
    draw_centered_text(p, sig_y - 20, "Authorized Signature", 
                      "Helvetica", 9, Color(0.5, 0.5, 0.5))

    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f'certificate_{certificate_code}.pdf',
                     mimetype='application/pdf')


@app.route('/admin/make-me-admin', methods=['POST', 'GET'])
@login_required
def make_me_admin():
    """Promote the currently logged-in user to admin if no admin exists yet.
    This is a safety valve for first-time setup. After the first admin exists,
    this route will deny further promotions unless the user is already admin.
    """
    # Check if any admin already exists
    existing_admins = mongo.db.users.count_documents({'is_admin': True})
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

    if request.method == 'GET':
        # Render a proper template so the button is visible
        return render_template('admin_make_me_admin.html', existing_admins=existing_admins)

    # POST
    if existing_admins > 0 and not user.get('is_admin', False):
        flash('An admin already exists. Ask an admin to promote you.', 'error')
        return redirect(url_for('dashboard'))

    # Promote current user to admin
    mongo.db.users.update_one({'_id': user['_id']}, {'$set': {'is_admin': True}})
    session['is_admin'] = True
    flash('You have been promoted to admin.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard - Management focused"""
    # User statistics
    total_users = mongo.db.users.count_documents({'is_admin': {'$ne': True}})
    total_admins = mongo.db.users.count_documents({'is_admin': True})
    
    # Course enrollment statistics
    all_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    total_enrollments = sum(len(user.get('courses', [])) for user in all_users)
    total_completions = sum(len([c for c in user.get('courses', []) if c.get('completed')]) for user in all_users)
    total_certificates = sum(len(user.get('certificates', [])) for user in all_users)
    
    # Assessment statistics
    total_assessments = sum(len(user.get('quiz_history', [])) for user in all_users)
    
    # Learning goal distribution
    goal_distribution = {}
    for user in all_users:
        goal = user.get('learning_goal', 'Not Set')
        goal_distribution[goal] = goal_distribution.get(goal, 0) + 1
    
    # Recent activity
    recent_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}).sort('created_at', -1).limit(5))
    
    # Recent assessments (from all users)
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
    
    # Sort by date and get most recent 10
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


@app.route('/admin/users')
@admin_required
def admin_users():
    """Admin user management"""
    users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    return render_template('admin_users.html', users=users)


@app.route('/admin/test-results')
@admin_required
def admin_test_results():
    """View all user test results - Admin only"""
    import os
    
    # Get all users (non-admin)
    all_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    
    # Compile all test results from all users
    all_test_results = []
    
    for user in all_users:
        quiz_history = user.get('quiz_history', [])
        for quiz in quiz_history:
            # Format quiz data with user info
            quiz_copy = quiz.copy()
            quiz_copy['user_id'] = str(user['_id'])
            quiz_copy['user_name'] = user.get('name', 'Unknown')
            quiz_copy['user_email'] = user.get('email', 'Unknown')
            
            # Convert datetime to ISO format for JSON
            if quiz_copy.get('date'):
                quiz_copy['date_formatted'] = quiz_copy['date'].strftime('%B %d, %Y at %I:%M %p')
                quiz_copy['date_iso'] = quiz_copy['date'].isoformat()
            
            all_test_results.append(quiz_copy)
    
    # Sort by date (most recent first)
    all_test_results.sort(key=lambda x: x.get('date', datetime.datetime.min), reverse=True)
    
    # Get test result files from Test Results folder
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


@app.route('/admin/certificates')
@admin_required
def admin_certificates():
    """Admin view of all user certificates."""
    # Get all non-admin users
    all_users = list(mongo.db.users.find({'is_admin': {'$ne': True}}))
    
    # Compile all certificates from all users
    all_certificates = []
    
    for user in all_users:
        certificates = user.get('certificates', [])
        for cert in certificates:
            cert_copy = cert.copy()
            cert_copy['user_id'] = str(user['_id'])
            cert_copy['user_name'] = user.get('name', 'Unknown')
            cert_copy['user_email'] = user.get('email', 'Unknown')
            
            # Normalize issued_date for sorting and display
            issued_date = cert_copy.get('issued_date') or cert_copy.get('completion_date')
            
            if issued_date:
                if isinstance(issued_date, str):
                    # Already a string, parse it
                    try:
                        cert_date = datetime.datetime.strptime(issued_date, '%Y-%m-%d')
                        cert_copy['issued_date_formatted'] = cert_date.strftime('%B %d, %Y')
                        cert_copy['issued_date_sort'] = cert_date  # For sorting
                    except:
                        cert_copy['issued_date_formatted'] = issued_date
                        cert_copy['issued_date_sort'] = datetime.datetime.min  # Fallback for sorting
                else:
                    # It's a datetime object
                    cert_copy['issued_date_formatted'] = issued_date.strftime('%B %d, %Y')
                    cert_copy['issued_date_sort'] = issued_date
            else:
                # No date available
                cert_copy['issued_date_formatted'] = 'Unknown'
                cert_copy['issued_date_sort'] = datetime.datetime.min
            
            # Ensure certificate_id exists (fallback to certificate_code for old certificates)
            if not cert_copy.get('certificate_id'):
                cert_copy['certificate_id'] = cert_copy.get('certificate_code', 'Unknown')
            
            # Ensure learning_goal exists
            if not cert_copy.get('learning_goal'):
                cert_copy['learning_goal'] = user.get('learning_goal', 'Unknown')
            
            all_certificates.append(cert_copy)
    
    # Sort by issued date (most recent first) using normalized date
    all_certificates.sort(key=lambda x: x.get('issued_date_sort', datetime.datetime.min), reverse=True)
    
    # Get unique learning goals for filtering
    unique_goals = list(set(cert.get('learning_goal', 'Unknown') for cert in all_certificates))
    unique_goals.sort()
    
    # Calculate statistics
    total_certificates = len(all_certificates)
    users_with_certs = len([u for u in all_users if u.get('certificates')])
    
    return render_template('admin_certificates.html',
                         all_certificates=all_certificates,
                         unique_goals=unique_goals,
                         total_certificates=total_certificates,
                         users_with_certs=users_with_certs,
                         total_users=len(all_users))


@app.route('/admin/revoke-certificate', methods=['POST'])
@admin_required
def admin_revoke_certificate():
    """Revoke a certificate from a user."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        certificate_id = data.get('certificate_id')
        
        if not user_id or not certificate_id:
            return jsonify({'success': False, 'message': 'Missing user_id or certificate_id'}), 400
        
        # Find the user
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Find and remove the certificate
        certificates = user.get('certificates', [])
        certificate_found = False
        updated_certificates = []
        
        for cert in certificates:
            if cert.get('certificate_id') == certificate_id:
                certificate_found = True
                # Skip this certificate (effectively removing it)
                continue
            updated_certificates.append(cert)
        
        if not certificate_found:
            return jsonify({'success': False, 'message': 'Certificate not found'}), 404
        
        # Update user's certificates
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'certificates': updated_certificates}}
        )
        
        return jsonify({
            'success': True, 
            'message': f'Certificate {certificate_id} has been revoked successfully'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin/view-certificate/<user_id>/<certificate_id>')
@admin_required
def admin_view_certificate(user_id, certificate_id):
    """Admin view any user's certificate as PDF"""
    # Find the user who owns the certificate
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    
    if not user:
        flash('User not found!', 'error')
        return redirect(url_for('admin_certificates'))
    
    certificates = user.get('certificates', [])
    
    # Find certificate by certificate_code OR certificate_id
    certificate = next(
        (cert for cert in certificates 
         if cert.get('certificate_code') == certificate_id 
         or cert.get('certificate_id') == certificate_id), 
        None
    )

    if not certificate:
        flash('Certificate not found!', 'error')
        return redirect(url_for('admin_certificates'))

    # Find the corresponding course to get instructor information
    course_title = certificate.get('course_title', 'Unknown Course')
    courses = user.get('courses', [])
    corresponding_course = next((c for c in courses if c.get('title') == course_title), None)
    
    # Get instructor name (fallback to certificate data or default)
    if corresponding_course and corresponding_course.get('instructor'):
        instructor_name = corresponding_course['instructor']
    elif certificate.get('instructor'):
        instructor_name = certificate['instructor']
    else:
        instructor_name = 'Expert Instructor'
    
    # Get course URL for creating channel link
    course_url = None
    if corresponding_course and corresponding_course.get('url'):
        course_url = corresponding_course['url']

    # Create PDF certificate (same logic as regular download_certificate)
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    # Certificate design
    width, height = letter  # 612 x 792 points

    # Helper function for centered text
    def draw_centered_text(canvas_obj, y_pos, text, font_name, font_size, color=None):
        """Draw text centered horizontally on the page"""
        if color:
            canvas_obj.setFillColor(color)
        canvas_obj.setFont(font_name, font_size)
        text_width = canvas_obj.stringWidth(text, font_name, font_size)
        x_pos = (width - text_width) / 2
        canvas_obj.drawString(x_pos, y_pos, text)

    # Outer border
    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(4)
    p.rect(40, 40, width - 80, height - 80)

    # Inner decorative border
    p.setStrokeColor(Color(0.8, 0.8, 0.8))
    p.setLineWidth(1)
    p.rect(55, 55, width - 110, height - 110)

    # Title - "CERTIFICATE OF COMPLETION"
    draw_centered_text(p, height - 120, "CERTIFICATE OF COMPLETION", 
                      "Helvetica-Bold", 32, Color(0.2, 0.4, 0.8))

    # Decorative line under title
    p.setStrokeColor(Color(0.2, 0.4, 0.8))
    p.setLineWidth(2)
    line_y = height - 135
    p.line(width / 2 - 180, line_y, width / 2 + 180, line_y)

    # "This is to certify that"
    draw_centered_text(p, height - 200, "This is to certify that", 
                      "Helvetica", 16, Color(0.3, 0.3, 0.3))

    # User name (prominent)
    user_name = user['name'].upper()
    draw_centered_text(p, height - 260, user_name, 
                      "Helvetica-Bold", 28, Color(0.1, 0.1, 0.1))

    # Decorative line under name
    p.setStrokeColor(Color(0.7, 0.7, 0.7))
    p.setLineWidth(1)
    p.setFont("Helvetica-Bold", 28)
    name_width = p.stringWidth(user_name, "Helvetica-Bold", 28)
    name_line_y = height - 275
    p.line(width / 2 - name_width / 2 - 15, name_line_y, 
           width / 2 + name_width / 2 + 15, name_line_y)

    # "has successfully completed the course"
    draw_centered_text(p, height - 320, "has successfully completed the course", 
                      "Helvetica", 16, Color(0.3, 0.3, 0.3))

    # Course title (with dynamic sizing and intelligent line wrapping)
    course_title = certificate['course_title']
    
    # Calculate optimal font size and wrapping based on title length
    title_length = len(course_title)
    
    if title_length <= 40:
        # Short title - use larger font, single line
        title_font_size = 20
        title_lines = [course_title]
        base_y = height - 370
    elif title_length <= 70:
        # Medium title - normal font, possibly 2 lines
        title_font_size = 18
        # Smart word wrap - check if it fits in one line first
        p.setFont("Helvetica-Bold", title_font_size)
        if p.stringWidth(course_title, "Helvetica-Bold", title_font_size) <= (width - 120):
            title_lines = [course_title]
        else:
            # Wrap to 2 lines
            words = course_title.split()
            lines = []
            current_line = ""
            for word in words:
                test_line = current_line + (" " + word if current_line else word)
                if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 120):
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)
            title_lines = lines[:2]  # Max 2 lines
        base_y = height - 370
    else:
        # Long title - smaller font, up to 3 lines
        title_font_size = 16
        words = course_title.split()
        lines = []
        current_line = ""
        p.setFont("Helvetica-Bold", title_font_size)
        for word in words:
            test_line = current_line + (" " + word if current_line else word)
            if p.stringWidth(test_line, "Helvetica-Bold", title_font_size) <= (width - 100):
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        title_lines = lines[:3]  # Max 3 lines
        base_y = height - 360  # Start slightly higher for more lines
    
    # Draw the course title lines
    line_spacing = title_font_size + 5  # Dynamic line spacing based on font size
    for i, line in enumerate(title_lines):
        y_position = base_y - (i * line_spacing)
        draw_centered_text(p, y_position, f'"{line}"' if i == 0 else line, 
                         "Helvetica-Bold", title_font_size, Color(0.2, 0.4, 0.8))
    
    # Calculate dynamic Y position for instructor based on number of title lines
    num_title_lines = len(title_lines)
    instructor_y = base_y - (num_title_lines * line_spacing) - 20  # 20pt gap after title

    # Instructor/Channel name (giving credit) with clickable link
    instructor_text = f"by {instructor_name}"
    p.setFillColor(Color(0.3, 0.3, 0.3))
    p.setFont("Helvetica-Oblique", 13)
    text_width = p.stringWidth(instructor_text, "Helvetica-Oblique", 13)
    x_pos = (width - text_width) / 2
    
    # Draw the text at dynamic position
    p.drawString(x_pos, instructor_y, instructor_text)
    
    # Add clickable link annotation if course URL exists
    if course_url:
        # Create a link annotation (clickable area)
        # Extract channel URL from video URL
        if 'youtube.com' in course_url or 'youtu.be' in course_url:
            # Try to extract channel URL
            # For now, link to the video itself as it shows the channel
            link_rect = (x_pos, instructor_y - 2, x_pos + text_width, instructor_y + 13)
            p.linkURL(course_url, link_rect, relative=0)
            
            # Underline to indicate it's a link
            p.setStrokeColor(Color(0.3, 0.3, 0.3))
            p.setLineWidth(0.5)
            p.line(x_pos, instructor_y - 1, x_pos + text_width, instructor_y - 1)

    # Calculate dynamic positions for date and certificate ID
    date_y = instructor_y - 45  # 45pt gap after instructor
    cert_id_y = date_y - 25  # 25pt gap after date

    # Completion date
    completion_date = certificate['completion_date'].strftime("%B %d, %Y")
    draw_centered_text(p, date_y, f"Completed on: {completion_date}", 
                      "Helvetica", 14, Color(0.4, 0.4, 0.4))

    # Certificate ID
    draw_centered_text(p, cert_id_y, f"Certificate ID: {certificate['certificate_code']}", 
                      "Helvetica", 12, Color(0.5, 0.5, 0.5))

    # Decorative elements (circles on sides) - positioned dynamically in middle
    circle_y = (height - 120 + cert_id_y) / 2  # Midpoint between title and bottom content
    # Left decoration
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(100, circle_y, 18, fill=1)

    # Right decoration
    p.setFillColor(Color(0.9, 0.9, 0.9))
    p.circle(width - 100, circle_y, 25, fill=1)
    p.setFillColor(Color(0.2, 0.4, 0.8))
    p.circle(width - 100, circle_y, 18, fill=1)

    # Platform name and tagline at bottom
    draw_centered_text(p, 140, "Personalized Education Platform", 
                      "Helvetica-Bold", 13, Color(0.5, 0.5, 0.5))
    draw_centered_text(p, 120, "Empowering Learners Worldwide", 
                      "Helvetica-Oblique", 11, Color(0.6, 0.6, 0.6))

    # Timestamp for authenticity (small, bottom left)
    p.setFillColor(Color(0.7, 0.7, 0.7))
    p.setFont("Helvetica", 7)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    p.drawString(50, 50, f"Generated: {timestamp}")

    # Signature line (optional decorative element)
    p.setStrokeColor(Color(0.5, 0.5, 0.5))
    p.setLineWidth(1)
    sig_y = 220
    p.line(width / 2 - 100, sig_y, width / 2 + 100, sig_y)
    draw_centered_text(p, sig_y - 20, "Authorized Signature", 
                      "Helvetica", 9, Color(0.5, 0.5, 0.5))

    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=False,
                     download_name=f'certificate_{certificate_id}.pdf',
                     mimetype='application/pdf')


@app.route('/admin/users/<user_id>', methods=['GET'])
@admin_required
def admin_user_detail(user_id):
    """Return user details as JSON (excluding sensitive fields)."""
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        # Build a safe payload without password/hash
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


@app.route('/admin/users/<user_id>/edit', methods=['POST'])
@admin_required
def admin_user_edit(user_id):
    """Edit user basic details (name, email, learning_goal, skill_level)."""
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip().lower()
        learning_goal = (data.get('learning_goal') or '').strip() or None
        # skill_level may be float percentage
        try:
            skill_level = float(data.get('skill_level')) if data.get('skill_level') is not None else None
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid skill level'}), 400

        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Prevent editing other admins via this endpoint (optional safety)
        if user.get('is_admin'):
            return jsonify({'success': False, 'message': 'Cannot edit admin user via this page'}), 403

        # Ensure email uniqueness if changed
        if email and email != user.get('email'):
            if mongo.db.users.find_one({'email': email, '_id': {'$ne': ObjectId(user_id)}}):
                return jsonify({'success': False, 'message': 'Email already in use'}), 400

        updates = {}
        if name:
            updates['name'] = name
        if email:
            updates['email'] = email
        # Allow clearing learning goal by passing empty string
        updates['learning_goal'] = learning_goal
        if skill_level is not None:
            # clamp 0-100
            updates['skill_level'] = max(0.0, min(100.0, skill_level))

        if not updates:
            return jsonify({'success': False, 'message': 'No changes provided'}), 400

        mongo.db.users.update_one({'_id': ObjectId(user_id)}, {'$set': updates})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/admin/users/<user_id>/delete', methods=['POST'])
@admin_required
def admin_user_delete(user_id):
    """Delete a user account (non-admin). Prevent deleting yourself."""
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Don't allow deleting admins here
        if user.get('is_admin', False):
            return jsonify({'success': False, 'message': 'Cannot delete an admin user'}), 403

        # Prevent deleting your own account via admin
        if str(user.get('_id')) == session.get('user_id'):
            return jsonify({'success': False, 'message': 'You cannot delete your own account here'}), 400

        mongo.db.users.delete_one({'_id': ObjectId(user_id)})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route('/api/dashboard-data')
@login_required
def dashboard_data():
    """API endpoint for dashboard charts"""
    user = mongo.db.users.find_one({'_id': ObjectId(session['user_id'])})

    # Quiz history for line chart
    quiz_history = user.get('quiz_history', [])
    quiz_data = {
        'labels': [q['date'].strftime('%m/%d') for q in quiz_history],
        'scores': [q['percentage'] for q in quiz_history]
    }

    # Course progress for doughnut chart
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


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile management"""
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
            return redirect(url_for('profile'))
        else:
            flash('Name and Email are required!', 'error')
            
    return render_template('profile.html', user=user)

# HTML Templates (save these as separate files in a 'templates' directory)

# templates/base.html
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Personalized Education Platform{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .navbar-brand { font-weight: bold; }
        .card { box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .progress-bar { transition: width 0.5s ease; }
        .certificate-card { border: 2px solid gold; background: linear-gradient(135deg, #f6f9fc 0%, #e9ecef 100%); }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('index') }}">
                <i class="fas fa-graduation-cap"></i> SkillSpree
            </a>
            <div class="navbar-nav ms-auto">
                {% if session.user_id %}
                    <a class="nav-link" href="{{ url_for('dashboard') }}">Dashboard</a>
                    <a class="nav-link" href="{{ url_for('certificates') }}">Certificates</a>
                    <a class="nav-link" href="{{ url_for('profile') }}">Profile</a>
                    <a class="nav-link" href="{{ url_for('logout') }}">Logout</a>
                {% else %}
                    <a class="nav-link" href="{{ url_for('login') }}">Login</a>
                    <a class="nav-link" href="{{ url_for('register') }}">Register</a>
                {% endif %}
            </div>
        </div>
    </nav>

    <main class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'danger' if category == 'error' else category }} alert-dismissible fade show">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
'''

# Additional templates would be created similarly...
# Due to space constraints, I'm showing the main application structure.
# The complete implementation would include all the HTML templates for:
# - index.html (landing page)
# - register.html (registration form)
# - login.html (login form)
# - onboarding.html (goal selection)
# - assessment.html (quiz interface)
# - assessment_results.html (quiz results and recommendations)
# - dashboard.html (main user dashboard with charts)
# - course.html (individual course view)
# - certificates.html (certificate gallery)
# - profile.html (user profile management)
# - admin_dashboard.html (admin overview)
# - admin_users.html (user management)
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))