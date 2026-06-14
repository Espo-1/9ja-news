from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import requests
import os

app = Flask(__name__)
CORS(app)

@app.route('/', methods=['GET'])
def index():
    return jsonify({ 'status': 'QuickSavePlus yt-dlp API running' })

@app.route('/fetch', methods=['POST'])
def fetch_media():
    data       = request.get_json(force=True)
    url        = data.get('url', '').strip()
    audio_only = data.get('audioOnly', False)

    if not url:
        return jsonify({ 'status': 'error', 'text': 'Missing url' }), 400

    ydl_opts = {
        'quiet':         True,
        'no_warnings':   True,
        'skip_download': True,
        'noplaylist':    True,
    }

    if audio_only:
        ydl_opts['format'] = 'bestaudio/best'
    else:
        ydl_opts['format'] = 'best[ext=mp4]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # Playlist / carousel
        if info.get('_type') == 'playlist':
            entries = info.get('entries', [])
            picker  = []
            for entry in entries:
                if not entry:
                    continue
                media_url = entry.get('url') or _best_url(entry)
                if media_url:
                    # Proxy the URL so the browser doesn't hit CDN directly
                    picker.append({
                        'url':   f"/proxy?url={requests.utils.quote(media_url, safe='')}",
                        'thumb': entry.get('thumbnail'),
                        'type':  'photo' if entry.get('ext') in ('jpg','jpeg','png','webp') else 'video',
                    })
            if picker:
                return jsonify({ 'status': 'picker', 'picker': picker })

        # Single media
        media_url = info.get('url') or _best_url(info)
        if not media_url:
            return jsonify({ 'status': 'error', 'text': 'No downloadable URL found' }), 404

        ext   = info.get('ext', 'mp4')
        title = info.get('title', 'video')
        thumb = info.get('thumbnail', '')

        # Proxy thumbnail to avoid CORS blocks
        proxy_thumb = f"/thumb?url={requests.utils.quote(thumb, safe='')}" if thumb else ''
        proxy_url   = f"/proxy?url={requests.utils.quote(media_url, safe='')}&title={requests.utils.quote(title, safe='')}&ext={ext}"

        return jsonify({
            'status':    'ok',
            'url':       proxy_url,
            'title':     title,
            'thumbnail': proxy_thumb,
            'duration':  info.get('duration'),
            'ext':       ext,
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if 'Private' in msg or 'private' in msg:
            text = 'This post is private.'
        elif 'login' in msg or 'sign in' in msg:
            text = 'This content requires login.'
        elif 'not available' in msg:
            text = 'This content is not available.'
        elif 'YouTube' in msg or 'youtube' in msg:
            text = 'YouTube is blocking this request. Try a different video.'
        else:
            text = 'Could not fetch this URL. Make sure it is public.'
        return jsonify({ 'status': 'error', 'text': text }), 422

    except Exception as e:
        return jsonify({ 'status': 'error', 'text': str(e) }), 500


@app.route('/thumb', methods=['GET'])
def proxy_thumb():
    """Proxy thumbnail images to avoid CDN CORS blocks."""
    thumb_url = request.args.get('url', '')
    if not thumb_url:
        return jsonify({ 'error': 'Missing url' }), 400
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer':    'https://www.google.com/',
        }
        upstream = requests.get(thumb_url, headers=headers, stream=True, timeout=10)
        upstream.raise_for_status()
        content_type = upstream.headers.get('Content-Type', 'image/jpeg')
        response = Response(stream_with_context(upstream.iter_content(1024 * 32)), content_type=content_type)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        return jsonify({ 'error': str(e) }), 500



def proxy_download():
    """Stream the media file through this server to avoid CDN auth issues."""
    media_url = request.args.get('url', '')
    title     = request.args.get('title', 'video')
    ext       = request.args.get('ext', 'mp4')

    if not media_url:
        return jsonify({ 'error': 'Missing url' }), 400

    try:
        headers = {
            'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer':         'https://www.google.com/',
            'Accept':          '*/*',
        }
        upstream = requests.get(media_url, headers=headers, stream=True, timeout=30)
        upstream.raise_for_status()

        content_type = upstream.headers.get('Content-Type', f'video/{ext}')
        safe_title   = title.replace('"', '').replace("'", '')[:60]

        def generate():
            for chunk in upstream.iter_content(chunk_size=1024 * 64):
                if chunk:
                    yield chunk

        response = Response(
            stream_with_context(generate()),
            content_type=content_type,
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{safe_title}.{ext}"'
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    except Exception as e:
        return jsonify({ 'error': str(e) }), 500


def _best_url(info):
    formats = info.get('formats', [])
    if not formats:
        return None
    for f in reversed(formats):
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            return f.get('url')
    for f in reversed(formats):
        if f.get('url'):
            return f.get('url')
    return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
