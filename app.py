import logging
from logging.config import dictConfig

import sets
import uuid

from flask import Flask, request, session, render_template, url_for
from flask_socketio import SocketIO, send, emit, join_room
from flask_session import Session

dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s %(filename)s:%(lineno)d: %(message)s',
    }},
    'root': {
        'level': 'INFO',
    }
})

app = Flask(__name__)
app.secret_key = 'top secret info'
app.config['TEMPLATES_AUTO_RELOAD'] = True
SESSION_TYPE='filesystem'
app.config.from_object(__name__)
Session(app)
socketio = SocketIO(app, manage_session=False)

GAMES = {}
PLAYERS = {}
UUIDS = {}


def create_game(owner_uuid, room):
  app.logger.info('Creating room %s with owner %s' % (room, owner_uuid))
  GAMES[room] = {'owner': owner_uuid, 'players': sets.Set()}
  GAMES[room]['players'].add(owner_uuid)


def join_game(sid, player_uuid, name, room):
  GAMES[room]['players'].add(player_uuid)
  PLAYERS[player_uuid] = {'room': room, 'name': name}
  UUIDS[player_uuid] = sid
  join_room(room)
  emit('join', {'name': name, 'room': room, 'game': url_for('game', room=room)})
  emit('add_player', {'player': [name]}, room=room)


def first_player(players):
  for x in players:
    return x


def leave_game(game, player_uuid):
  if not game in GAMES:
    return
  GAMES[game]['players'].discard(player_uuid)
  if player_uuid in PLAYERS:
    del PLAYERS[player_uuid]
  if player_uuid in UUIDS:
    del UUIDS[player_uuid]
  if player_uuid == GAME[game]['owner']:
    if len(GAME[game]['players']) == 0:
      del GAME[game]
      return
    GAME[game]['owner'] = first_player(GAME[game]['players'])


@socketio.on('connect')
def handle_connect():
  app.logger.info('connect %s %s' % (request.sid, str(session)))
  if 'uuid' in session and session['uuid'] in PLAYERS:
    info = PLAYERS[session['uuid']]
    join_game(request.sid, session['uuid'], info['name'], info['room'])


@socketio.on('join')
def handle_join(json):
  app.logger.info('join %s %s' % (str(json), str(session)))
  try:
    if not json['name'] or not json['room']:
      emit('error', {'msg': 'Invalid request.'})
      return
  except KeyError:
    emit('error', {'msg': 'Invalid request.'})
    return
  if not 'uuid' in session:
    session['uuid'] = uuid.uuid4()
  if 'uuid' in session and session['uuid'] in PLAYERS:
    emit('error', {msg: 'Already in a game!'});
    return
  if not json['room'] in GAMES:
    create_game(session['uuid'], json['room'])
  join_game(request.sid, session['uuid'], json['name'], json['room'])
  app.logger.info('join %s %s' % (str(json), str(session)))


@socketio.on('leave')
def handle_leave():
  app.logger.info('leave') 
  if 'uuid' in session and session['uuid'] in PLAYERS:
    leave_game(PLAYERS[session['uuid']]['room'], session['uuid'])


@socketio.on('start')
def handle_start():
  app.logger.info('start')
  if request.sid in PLAYERS and PLAYERS[request.sid] in GAMES:
    if GAMES[PLAYERS[request.sid]]['owner'] != request.sid:
      return
    GAMES[PLAYERS[request.sid]]['game'].start()


@socketio.on('end')
def handle_end():
  app.logger.info('end')
  if request.sid in PLAYERS and PLAYERS[request.sid] in GAMES:
    if GAMES[PLAYERS[request.sid]]['owner'] != request.sid:
      return
    GAMES[PLAYERS[request.sid]]['game'].end()


@socketio.on('get_players')
def handle_get_players():
  app.logger.error('get_players ' + str(session) + ' ' + str(PLAYERS))
  if not 'uuid' in session or not session['uuid'] in PLAYERS:
    emit('error', {'msg': 'Not in a game!'})
    return
  app.logger.error('get_players wtf')
  p = PLAYERS[session['uuid']]
  app.logger.error('get_players ' + str(list(GAMES[p['room']]['players'])))
  emit('add_player', {'player': [PLAYERS[x]['name'] for x in GAMES[p['room']]['players']]})


@app.route('/game', methods=['GET'])
def game():
  game = request.args.get('room')
  app.logger.error('game ' + str(GAMES))
  if not game in GAMES:
    return 'Game not found', 404
  if not 'uuid' in session:
    return 'Have not joined a game!', 404
  if not session['uuid'] in PLAYERS or PLAYERS[session['uuid']]['room'] != game:
    return 'Wrong game.', 404
  return render_template('game.html')


@app.route('/', methods=['GET'])
def main():
  return render_template('main.html')


if __name__ == '__main__':
  socketio.run(app)
