import json
import google.generativeai as genai
from config import Config
from app.youtube_utils import search_youtube_videos, verify_youtube_video_exists

genai.configure(api_key=Config.GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

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
        
        if not response_text.startswith('['):
            start = response_text.find('[')
            end = response_text.rfind(']') + 1
            if start != -1 and end != 0:
                response_text = response_text[start:end]
        
        questions = json.loads(response_text)
        
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
            return None
            
    except Exception as e:
        print(f"Error generating quiz questions: {e}")
        return None


def get_course_recommendations(learning_goal, skill_level, quiz_results, is_regeneration=False):
    """
    Get personalized course recommendations using Gemini API with skill-level adaptation
    """
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
    
    print(f"Debug - Requesting AI recommendations for {learning_goal}")
    print(f"Debug - User is {level_desc} (score: {skill_level}/100)")
    
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
        
        validated_courses = []
        
        for i, search_query_data in enumerate(raw_courses):
            search_query = search_query_data.get('search_query', '').strip()
            channel_hint = search_query_data.get('channel_name', '').strip()
            topics = search_query_data.get('topics', [])
            
            if not search_query:
                print(f"Debug - Search query {i+1}: Missing search_query field")
                continue
            
            print(f"Debug - Searching YouTube for: '{search_query}'")
            
            search_results = search_youtube_videos(search_query, max_results=1)
            
            if not search_results:
                print(f"Debug - No results found for: '{search_query}'")
                continue
            
            video = search_results[0]
            video_id = video['video_id']
            
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
        
        if len(validated_courses) >= 2:
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
