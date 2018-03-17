from gevent import monkey
monkey.patch_all()
import argparse
import traceback
import flask
import flask_login
import sys
import psutil
import os
import pathlib
import shutil
import inspect
import json
import pymongo
from pymongo import ASCENDING, DESCENDING
import datetime
import pytz
import time
import logging
from bson.json_util import loads, dumps


def utc_now():
    return datetime.datetime.now(pytz.utc)


def get_config(_config_file='config.json'):
    """
        load config data in json format
    """
    try:
        ''' script absolute location '''
        abs_path = os.path.dirname(inspect.getfile(inspect.currentframe()))

        if _config_file[0] not in ('/', '~'):
            if os.path.isfile(os.path.join(abs_path, _config_file)):
                config_path = os.path.join(abs_path, _config_file)
            else:
                raise IOError('Failed to find config file')
        else:
            if os.path.isfile(_config_file):
                config_path = _config_file
            else:
                raise IOError('Failed to find config file')

        with open(config_path) as cjson:
            config_data = json.load(cjson)
            # config must not be empty:
            if len(config_data) > 0:
                return config_data
            else:
                raise Exception('Failed to load config file')

    except Exception as _e:
        print(_e)
        raise Exception('Failed to read in the config file')


def connect_to_db(_config):
    """ Connect to the mongodb database

    :return:
    """
    try:
        if _config['server']['environment'] == 'production':
            # in production, must set up replica set
            _client = pymongo.MongoClient(host=_config['database']['host'], port=_config['database']['port'],
                                          replicaset=_config['database']['replicaset'],
                                          readPreference='primaryPreferred')
        else:
            # standalone from my laptop, when there's only one instance of DB
            _client = pymongo.MongoClient(host=_config['database']['host'], port=_config['database']['port'])
        # grab main database:
        _db = _client[_config['database']['db']]
    except Exception as _e:
        raise ConnectionRefusedError
    try:
        # authenticate
        _db.authenticate(_config['database']['user'], _config['database']['pwd'])
    except Exception as _e:
        raise ConnectionRefusedError

    return _client, _db


''' config '''
# FIXME:
config = get_config(_config_file='/Users/dmitryduev/_caltech/python/jspoc/config.local.json')


''' initialize the Flask app '''
app = flask.Flask(__name__)
# if run in a sub-url
# app.wsgi_app = ReverseProxied(app.wsgi_app)
# add 'do' statement to jinja environment (does the same as {{ }}, but returns nothing):
app.jinja_env.add_extension('jinja2.ext.do')

app.secret_key = config['server']['SECRET_KEY']


def get_db(_config):
    """
        Opens a new database connection if there is none yet for the current application context.
    """
    if not hasattr(flask.g, 'client'):
        flask.g.client, flask.g.db = connect_to_db(_config)
    return flask.g.client, flask.g.db


@app.teardown_appcontext
def close_db(error):
    """
        Closes the database again at the end of the request.
    """
    if hasattr(flask.g, 'client'):
        flask.g.client.close()


''' web GUI '''
# login management
login_manager = flask_login.LoginManager()
login_manager.init_app(app)


class User(flask_login.UserMixin):
    pass


@login_manager.user_loader
def user_loader(username):
    # username roboao?
    if str(username) != config['server']['user']:
        return

    user = User()
    user.id = username
    return user


@login_manager.request_loader
def request_loader(request):
    username = request.form.get('username')
    if str(username) != config['server']['user']:
        return

    user = User()
    user.id = username

    try:
        user.is_authenticated = str(flask.request.form['password']).strip() == config['server']['pwd']
    except Exception as _e:
        print(_e)
        return

    return user


def stream_template(template_name, **context):
    """
        see: http://flask.pocoo.org/docs/0.11/patterns/streaming/
    :param template_name:
    :param context:
    :return:
    """
    app.update_template_context(context)
    t = app.jinja_env.get_template(template_name)
    rv = t.stream(context)
    rv.enable_buffering(5)
    return rv


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
        Endpoint for login through the web interface
    :return:
    """
    if flask.request.method == 'GET':
        # logged in already?
        if flask_login.current_user.is_authenticated:
            return flask.redirect(flask.url_for('root'))
        # serve template if not:
        else:
            return flask.render_template('template-login.html', logo=config['server']['logo'])
    # print(flask.request.form['username'], flask.request.form['password'])

    # print(flask.request)

    username = flask.request.form['username']
    password = flask.request.form['password']
    if (username == config['server']['user']) and (password == config['server']['pwd']):
        user = User()
        user.id = username
        flask_login.login_user(user, remember=True)
        return flask.redirect(flask.url_for('root'))
    else:
        # serve template with flag fail=True to display fail message
        return flask.render_template('template-login.html', logo=config['server']['logo'],
                                     messages=[(u'Failed to log in.', u'danger')])


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    flask_login.logout_user()
    return flask.redirect(flask.url_for('root'))


# serve root
@app.route('/', methods=['GET', 'POST'])
@flask_login.login_required
def root():

    if 'date' in flask.request.args:
        date = flask.request.args['date']
        # check that date is ok:
        try:
            datetime.datetime.strptime(date, '%Y%m%d')
        except Exception as e:
            print(e)
            date = datetime.datetime.utcnow().strftime('%Y%m%d')
    else:
        date = datetime.datetime.utcnow().strftime('%Y%m%d')
        # date = '20180316'

    # get db connection
    client, db = get_db(config)

    messages = []

    # get today's report:
    report = None

    return flask.Response(stream_template('template-root.html',
                                          logo=config['server']['logo'],
                                          date=date,
                                          current_year=datetime.datetime.now().year,
                                          messages=messages))


@app.errorhandler(500)
def internal_error(error):
    return '500 error'


@app.errorhandler(404)
def not_found(error):
    return '404 error'


@app.errorhandler(403)
def not_found(error):
    return '403 error: forbidden'


@login_manager.unauthorized_handler
def unauthorized_handler():
    return flask.redirect(flask.url_for('login'))


if __name__ == '__main__':
    app.run(host=config['server']['host'], port=config['server']['port'], threaded=True)