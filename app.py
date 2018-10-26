import logging
import random
import uuid

from flask import Flask, request, session, render_template, url_for
from flask.logging import default_handler
from flask_socketio import SocketIO, send, emit, join_room
from flask_session import Session

app = Flask(__name__)
default_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(filename)s:%(lineno)d: %(message)s'))
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
  GAMES[room] = {'owner': owner_uuid, 'players': set()}
  GAMES[room]['started'] = False
  GAMES[room]['victim'] = None
  GAMES[room]['conspiracy_probability'] = random.random()


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
  name = None
  room = None
  if player_uuid in PLAYERS:
    name = PLAYERS[player_uuid]['name']
    room = PLAYERS[player_uuid]['room']
    del PLAYERS[player_uuid]
  if player_uuid in UUIDS:
    del UUIDS[player_uuid]
  if player_uuid == GAMES[game]['owner']:
    if len(GAMES[game]['players']) == 0:
      del GAMES[game]
      return
    owner = first_player(GAMES[game]['players'])
    GAMES[game]['owner'] = owner
    if  room:
      emit('owner', {'player': name}, room=room)
    if name:
      emit('del_player', {'player': name})


@socketio.on('connect')
def handle_connect():
  app.logger.info('connect %s %s' % (request.sid, str(session)))
  if 'uuid' in session and session['uuid'] in PLAYERS:
    info = PLAYERS[session['uuid']]
    join_game(request.sid, session['uuid'], info['name'], info['room'])
    p = PLAYERS[session['uuid']]
    g = GAMES[p['room']]
    if g['started']:
      emit('start', {'victim': PLAYERS[g['victim']]['name'] if g['victim'] != session['uuid'] else ''})


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
  if 'uuid' in session and session['uuid'] in PLAYERS:
    emit('error', {'msg': 'Already in a game!'});
    return
  if not 'uuid' in session:
    session['uuid'] = uuid.uuid4()
  if not json['room'] in GAMES:
    create_game(session['uuid'], json['room'])
  g= GAMES[json['room']]
  if g['started']:
    emit('error', {'msg': 'Game already started!'})
    return
  names = [PLAYERS[x]['name'] for x in g['players']]
  if json['name'] in names:
    emit('error', {'msg': 'Name already in use!'})
    return
  join_game(request.sid, session['uuid'], json['name'], json['room'])
  app.logger.info('join %s %s' % (str(json), str(session)))


@socketio.on('leave')
def handle_leave():
  app.logger.info('leave ' + str(session))
  if 'uuid' in session and session['uuid'] in PLAYERS:
    leave_game(PLAYERS[session['uuid']]['room'], session['uuid'])


@socketio.on('start')
def handle_start():
  app.logger.info('start')
  if not 'uuid' in session or not session['uuid'] in PLAYERS:
    emit('error', {'msg': 'Not in a game!'})
    return
  p = PLAYERS[session['uuid']]
  g = GAMES[p['room']]
  if g['owner'] != session['uuid']:
    emit('error', {'msg': 'Not owner!'})
    return
  if g['started']:
    emit('error', {'msg': 'Game already started!'})
    return
  conspiracy = random.random() >= g['conspiracy_probability']
  if conspiracy:
    victim = random.choice(list(g['players']))
    victim_name = PLAYERS[victim]['name']
  else:
    victim_name = ''
    victim = None
  g['victim'] = victim
  for player in g['players']:
    emit('start',{'victim': victim_name if player != victim else ''}, room=UUIDS[player])
  g['started'] = True
  app.logger.info('Game %s started. Victim=%s', p['room'], victim)


@socketio.on('end')
def handle_end():
  app.logger.info('end')
  if not 'uuid' in session or not session['uuid'] in PLAYERS:
    emit('error', {'msg': 'Not in a game!'})
    return
  p = PLAYERS[session['uuid']]
  g = GAMES[p['room']]
  if g['owner'] != session['uuid']:
    emit('error', {'msg': 'Not owner!'})
    return
  if not g['started']:
    emit('error', {'msg': 'Game not started!'})
    return
  g['started'] = False
  g['victim'] = None
  emit('end', room=p['room'])


@socketio.on('get_players')
def handle_get_players():
  app.logger.info('get_players ' + str(session) + ' ' + str(PLAYERS))
  if not 'uuid' in session or not session['uuid'] in PLAYERS:
    emit('error', {'msg': 'Not in a game!'})
    return
  p = PLAYERS[session['uuid']]
  app.logger.info('get_players ' + str(list(GAMES[p['room']]['players'])))
  emit('add_player', {'player': [PLAYERS[x]['name'] for x in GAMES[p['room']]['players']], 'me': p['name']})
  emit('owner', {'player': PLAYERS[GAMES[p['room']]['owner']]['name']})


@socketio.on('kick')
def handle_kick(json):
  app.logger.info('get_players ' + str(session) + ' ' + str(json))
  if not 'player' in json:
    emit('error', {'msg': 'Malformed request!'})
    return
  if session['uuid'] not in PLAYERS:
    emit('error', {'msg': 'Not in game!'})
    return
  g = GAMES[PLAYERS[session['uuid']]['room']]
  if g['owner'] != session['uuid']:
    emit('error', {'msg': 'Not game owner!'})
    return
  uuids = list(g['players'])
  names = [PLAYERS[x]['name'] for x in uuids]
  name_map = dict(zip(names, uuids))
  app.logger.info('names ' + str(name_map))
  if not json['player'] in name_map:
    emit('error', {'msg': 'Player not in game!'})
    return
  emit('kicked', room=UUIDS[name_map[json['player']]])
  leave_game(PLAYERS[session['uuid']]['room'], name_map[json['player']])


@app.route('/game', methods=['GET'])
def game():
  game = request.args.get('room')
  app.logger.info('game ' + str(GAMES))
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
