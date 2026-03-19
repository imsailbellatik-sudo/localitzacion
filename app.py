from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import re
import json
import os
import time
from datetime import datetime
import logging
from PIL import Image
import io
import exifread

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InstagramTracker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def extract_ip_from_profile(self, username):
        """Extract IP from Instagram profile using various methods"""
        try:
            # Method 1: Direct profile access
            profile_url = f"https://www.instagram.com/{username}/"
            response = self.session.get(profile_url, timeout=10)
            
            # Look for IPs in script tags or metadata
            ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
            ips = re.findall(ip_pattern, response.text)
            
            # Filter out common false positives
            filtered_ips = [ip for ip in ips if not ip.startswith('0.') and ip != '127.0.0.1']
            
            if filtered_ips:
                return filtered_ips[0]
            
            # Method 2: Extract from image URLs
            image_urls = re.findall(r'https?://[^\s"\']+\.(?:jpg|jpeg|png|gif)', response.text)
            for img_url in image_urls[:5]:
                match = re.search(ip_pattern, img_url)
                if match:
                    return match.group()
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting IP: {str(e)}")
            return None
    
    def get_instagram_data(self, username):
        """Fetch Instagram user data using unofficial methods"""
        try:
            # Using unofficial API endpoint (this may break if Instagram changes their API)
            api_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            
            headers = {
                'X-IG-App-ID': '936619743392459',
                'X-ASBD-ID': '198387',
                'X-IG-WWW-Claim': '0',
                'Origin': 'https://www.instagram.com',
                'Referer': f'https://www.instagram.com/{username}/',
                'Accept': 'application/json'
            }
            
            response = self.session.get(api_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                return response.json()
            else:
                # Fallback: Try to parse HTML
                return self.parse_profile_html(username)
                
        except Exception as e:
            logger.error(f"Error fetching Instagram data: {str(e)}")
            return None
    
    def parse_profile_html(self, username):
        """Parse HTML for fallback data extraction"""
        try:
            profile_url = f"https://www.instagram.com/{username}/"
            response = self.session.get(profile_url)
            
            # Extract basic info from HTML
            data = {
                'username': username,
                'exists': 'login' in response.text.lower(),
                'profile_data': {}
            }
            
            # Look for JSON-LD data
            json_ld_pattern = r'<script type="application/ld\+json">(.*?)</script>'
            matches = re.findall(json_ld_pattern, response.text, re.DOTALL)
            
            if matches:
                try:
                    json_data = json.loads(matches[0])
                    data['profile_data'] = json_data
                except:
                    pass
            
            return data
            
        except Exception as e:
            logger.error(f"Error parsing HTML: {str(e)}")
            return None
    
    def geolocate_ip(self, ip_address):
        """Convert IP to geographic location using multiple services"""
        services = [
            f"http://ip-api.com/json/{ip_address}",
            f"https://ipinfo.io/{ip_address}/json",
            f"https://geolocation-db.com/json/{ip_address}"
        ]
        
        for service_url in services:
            try:
                response = requests.get(service_url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    
                    if 'city' in data or 'loc' in data:
                        # Standardize response format
                        location_data = {
                            'ip': ip_address,
                            'city': data.get('city', 'Unknown'),
                            'region': data.get('region', data.get('regionName', 'Unknown')),
                            'country': data.get('country', data.get('country_name', 'Unknown')),
                            'isp': data.get('isp', data.get('org', 'Unknown')),
                            'coordinates': data.get('loc', '0,0')
                        }
                        
                        if 'lat' in data and 'lon' in data:
                            location_data['coordinates'] = f"{data['lat']},{data['lon']}"
                        
                        return location_data
            except:
                continue
        
        return None
    
    def analyze_photos_for_location(self, username):
        """Analyze Instagram photos for GPS metadata"""
        try:
            # Get recent posts
            profile_url = f"https://www.instagram.com/{username}/"
            response = self.session.get(profile_url)
            
            # Extract image URLs
            image_pattern = r'"display_url":"(https://[^"]+\.(?:jpg|jpeg|png))"'
            image_urls = re.findall(image_pattern, response.text)[:3]
            
            for img_url in image_urls:
                try:
                    # Download image
                    img_response = requests.get(img_url, timeout=10)
                    img_data = img_response.content
                    
                    # Extract EXIF data
                    tags = exifread.process_file(io.BytesIO(img_data))
                    
                    if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
                        # Convert EXIF coordinates to decimal
                        lat = self.convert_to_degrees(tags['GPS GPSLatitude'].values)
                        lon = self.convert_to_degrees(tags['GPS GPSLongitude'].values)
                        
                        if tags['GPS GPSLatitudeRef'].values != 'N':
                            lat = -lat
                        if tags['GPS GPSLongitudeRef'].values != 'E':
                            lon = -lon
                        
                        return {
                            'source': 'photo_metadata',
                            'coordinates': f"{lat},{lon}",
                            'accuracy': 'High (from photo GPS)'
                        }
                        
                except Exception as e:
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing photos: {str(e)}")
            return None
    
    def convert_to_degrees(self, value):
        """Convert EXIF coordinates to decimal degrees"""
        d = float(value[0].num) / float(value[0].den)
        m = float(value[1].num) / float(value[1].den)
        s = float(value[2].num) / float(value[2].den)
        return d + (m / 60.0) + (s / 3600.0)

tracker = InstagramTracker()

@app.route('/track', methods=['POST'])
def track_location():
    """Main tracking endpoint"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        
        if not username:
            return jsonify({
                'success': False,
                'error': 'No username provided'
            })
        
        logger.info(f"Tracking request for: {username}")
        
        # Method 1: Try to get IP from profile
        ip_address = tracker.extract_ip_from_profile(username)
        
        # Method 2: Analyze photos for GPS data
        photo_location = tracker.analyze_photos_for_location(username)
        
        # Method 3: Get Instagram data
        instagram_data = tracker.get_instagram_data(username)
        
        # Prepare response
        response_data = {
            'success': True,
            'username': username,
            'timestamp': datetime.now().isoformat(),
            'instagram_data': instagram_data is not None
        }
        
        if ip_address:
            # Geolocate the IP
            location = tracker.geolocate_ip(ip_address)
            
            if location:
                response_data.update({
                    'ip': ip_address,
                    'location': f"{location['city']}, {location['region']}, {location['country']}",
                    'coordinates': location['coordinates'],
                    'isp': location['isp'],
                    'accuracy': 'Medium (IP-based)',
                    'last_active': 'Recently active'
                })
        
        elif photo_location:
            # Use photo GPS data
            response_data.update({
                'ip': 'Not available',
                'location': 'Extracted from photo metadata',
                'coordinates': photo_location['coordinates'],
                'accuracy': photo_location['accuracy'],
                'last_active': 'Based on photo timestamp'
            })
        
        else:
            # Fallback: Use Instagram API data
            if instagram_data and 'profile_data' in instagram_data:
                # Extract any location info from profile
                profile = instagram_data.get('profile_data', {})
                
                location_info = profile.get('address', {}) if isinstance(profile.get('address'), dict) else {}
                
                response_data.update({
                    'ip': 'Not available',
                    'location': location_info.get('addressLocality', 'Unknown'),
                    'coordinates': '0,0',
                    'accuracy': 'Low (profile-based)',
                    'last_active': 'Unknown'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Could not retrieve location data'
                })
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Tracking error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        })

@app.route('/generate-tracking-link', methods=['POST'])
def generate_tracking_link():
    """Generate a tracking link for sending to target"""
    data = request.get_json()
    username = data.get('username')
    
    # Create a unique tracking ID
    tracking_id = os.urandom(16).hex()
    
    # Store tracking info (in production, use a database)
    tracking_data = {
        'id': tracking_id,
        'username': username,
        'created_at': datetime.now().isoformat(),
        'clicks': 0,
        'ips': []
    }
    
    # Create tracking link
    tracking_link = f"https://your-domain.com/track/{tracking_id}"
    
    return jsonify({
        'success': True,
        'tracking_link': tracking_link,
        'tracking_id': tracking_id
    })

@app.route('/track/<tracking_id>')
def track_click(tracking_id):
    """Endpoint for tracking pixel/clicks"""
    # Log the visitor's IP
    visitor_ip = request.remote_addr
    
    # In production: Store in database
    logger.info(f"Tracking ID: {tracking_id}, IP: {visitor_ip}")
    
    # Return a 1x1 transparent pixel
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    
    return send_file(
        io.BytesIO(pixel),
        mimetype='image/gif',
        as_attachment=False
    )

if __name__ == '__main__':
    # Run the application
    app.run(host='0.0.0.0', port=5000, debug=True)
