from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import os

app = Flask(__name__)
CORS(app)  # Cloudflare Worker will call this, so open CORS is fine

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
        'quiet':           True,
        'no_warnings':     True,
        'skip_download':   True,   # we only want the info/URLs
        'noplaylist':      True,
    }

    if audio_only:
        ydl_opts['format'] = 'bestaudio/best'
    else:
        # Best video+audio merged, fall back to best single file
        ydl_opts['format'] = 'bestvideo+bestaudio/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # ── Playlist / carousel (Instagram multi-image, etc.) ──
        if info.get('_type') == 'playlist':
            entries = info.get('entries', [])
            picker  = []
            for entry in entries:
                if not entry:
                    continue
                media_url = entry.get('url') or _best_url(entry)
                if media_url:
                    picker.append({
                        'url':   media_url,
                        'thumb': entry.get('thumbnail'),
                        'type':  'photo' if entry.get('ext') in ('jpg','jpeg','png','webp') else 'video',
                    })
            if picker:
                return jsonify({ 'status': 'picker', 'picker': picker })

        # ── Single media ──
        media_url = info.get('url') or _best_url(info)
        if not media_url:
            return jsonify({ 'status': 'error', 'text': 'No downloadable URL found' }), 404

        return jsonify({
            'status':    'ok',
            'url':       media_url,
            'title':     info.get('title', ''),
            'thumbnail': info.get('thumbnail', ''),
            'duration':  info.get('duration'),
            'ext':       info.get('ext', 'mp4'),
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        # Give friendly messages for common errors
        if 'Private' in msg or 'private' in msg:
            text = 'This post is private.'
        elif 'login' in msg or 'sign in' in msg:
            text = 'This content requires login.'
        elif 'not available' in msg:
            text = 'This content is not available.'
        else:
            text = 'Could not fetch this URL. Make sure it is public.'
        return jsonify({ 'status': 'error', 'text': text }), 422

    except Exception as e:
        return jsonify({ 'status': 'error', 'text': str(e) }), 500


def _best_url(info):
    """Pick the best format URL from an info dict."""
    formats = info.get('formats', [])
    if not formats:
        return None
    # Prefer formats that have both video and audio
    for f in reversed(formats):
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            return f.get('url')
    # Fall back to any format with a URL
    for f in reversed(formats):
        if f.get('url'):
            return f.get('url')
    return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
