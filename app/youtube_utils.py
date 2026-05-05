import re
import requests
from typing import Optional

def validate_youtube_video_id(video_id):
    """
    Validate if a YouTube video ID has the correct format
    Returns True if valid format, False otherwise
    """
    if not video_id or len(video_id) != 11:
        return False
    if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
        return True
    return False

def search_youtube_videos(search_query, api_key="AIzaSyAQvd9bhuAFHmzxnpg7xqxhA_avSoDJqnE", max_results=3):
    """
    Search for YouTube videos using YouTube Data API v3 Search endpoint
    """
    try:
        search_url = f"https://www.googleapis.com/youtube/v3/search"
        params = {
            'part': 'snippet',
            'q': search_query,
            'type': 'video',
            'videoDuration': 'long',
            'maxResults': max_results,
            'key': api_key,
            'order': 'relevance'
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
        
        if not data.get('items'):
            print(f"Debug - Video {video_id} not found on YouTube")
            return None
        
        video_info = data['items'][0]
        status = video_info.get('status', {})
        snippet = video_info.get('snippet', {})
        content_details = video_info.get('contentDetails', {})
        
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
    if re.match(r'^[a-zA-Z0-9_-]{11}$', candidate):
        return candidate
    try:
        if 'youtu.be/' in candidate:
            vid = candidate.split('youtu.be/')[-1].split('?')[0].split('/')[0]
            return vid if re.match(r'^[a-zA-Z0-9_-]{11}$', vid) else None
        if 'youtube.com' in candidate:
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
