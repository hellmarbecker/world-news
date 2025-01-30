import yaml
import json
import random
import math
from scipy import interpolate
import time
import argparse, sys, logging
import socket
import signal
from faker import Faker
from confluent_kafka import Producer
from confluent_kafka.serialization import StringSerializer, SerializationContext, MessageField, Serializer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.schema_registry.json_schema import JSONSerializer
# from confluent_kafka.schema_registry.protobuf import ProtobufSerializer
from mergedeep import merge


baseurl = "https://world-news.com"
fake = Faker()

# Attribute selector dicts. Key is the attribute value, value is the probability of occurrence.
# Probabilities must add up to 1.
# These have now been moved to the config file

# d_channel = { 'social media': 0.3, 'organic search': 0.2, 'paid search': 0.3, 'display': 0.1, 'affiliate': 0.1 } 
# d_campaign = { 'fb-1 Be Informed': 0.3, 'fb-2 US Election': 0.4, 'af-1 Latest News': 0.2, 'google-1 Be Informed': 0.1 }
# d_gender = { 'm': 0.5, 'w': 0.5 }
# d_age = { '18-25': 0.1, '26-35': 0.1, '36-50': 0.4, '51-60': 0.3, '61+': 0.1 }

d_statuscode = { '200': 0.9, '404': 0.05, '500': 0.05 }
l_content = "News Comment World Business Sport Puzzle Law".split()

reconfigure = False

# Signal handlers

def hupHandler(signum, frame):
    global reconfigure
    reconfigure = True
    logging.debug("in signal handler: SIGHUP received!")

# Exception classes

class DataGeneratorError(Exception):
    "Base exception for this project, all exceptions that can be raised inherit from this class."

class GeneratorConfigError(DataGeneratorError):
    "Invalid data generator configuration."

class InvalidStateException(DataGeneratorError):
    "The current model state value is not mapped to a state definition."

class InvalidTransitionException(DataGeneratorError):
    "No legal transition."

# Attribute selector function

def selectAttr(d):

    x = random.random()
    cume = 0.0
    sel = None

    for k, p in d.items():
        cume += p
        if cume >= x:
            sel = k
            break
    return sel

# Session model

class Session:
        
    def __init__(self, states, initialState, stateTransitionMatrix, **kwargs):
        if initialState not in states:
            raise InvalidStateException()
        self.startTime = None # this is set upon the first advance() to match the first eventTime
        self.states = states
        self.state = initialState
        self.statesVisited = [ initialState ] # this is going to be an ordered list of all the session states we visited in this session
        self.stateTransitionMatrix = stateTransitionMatrix
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return "{}({!r})".format(type(self).__name__, self.__dict__)

    def advance(self):
        newState = selectAttr(self.stateTransitionMatrix[self.state])
        if newState is None:
            raise InvalidTransitionException()
        self.eventTime = int(time.time())
        if self.startTime is None:
            self.startTime = self.eventTime
        logging.debug(f'advance(): from {self.state} to {newState}')
        contentId = random.choice(l_content)
        subContentId = fake.sentence(nb_words=6)[:-1]
        self.state = newState
        self.statesVisited.append(newState)

    def url(self):
        return baseurl + '/' + self.state + '/' + self.contentId + '/' + self.subContentId.replace(' ', '-')

# User model

class User:

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return "{}({!r})".format(type(self).__name__, self.__dict__)
   

# Serializers for schema support

class PlainJSONSerializer(Serializer): # serialize json without schema registry

    def __call__(self, obj, ctx=None):

        return json.dumps(obj)


def srSerializer(config, item): # item is click or session

    if "SchemaRegistry" in config and "enableSchemaRegistry" in config["SchemaRegistry"] and config["SchemaRegistry"]["enableSchemaRegistry"]:
        schema_registry_conf = {'url': config["SchemaRegistry"]["url"]}
        schema_registry_client = SchemaRegistryClient(schema_registry_conf)

        schemaPath = config["SchemaRegistry"]["schemaFile"][item]
        with open(schemaPath) as f:
            schema_str = f.read()
            # TODO this has no error handling at all!

        match config["SchemaRegistry"]["schemaType"]:
            case "avro":
                s = AvroSerializer(schema_registry_client, schema_str)
            case "json":
                s = JSONSerializer(schema_str, schema_registry_client)
            case "protobuf":
                # s = ProtobufSerializer(user_pb2.User, schema_registry_client, {'use.deprecated.format': False})
                logging.error(f'Unsupported serializer {config["SchemaRegistry"]["schemaType"]}')
                s = None
            case _:
                logging.error(f'Unknown serializer {config["SchemaRegistry"]["schemaType"]}')
                s = None
    else:
        s = PlainJSONSerializer()

    logging.debug(f'serializer for {item} is {s}')
    return s

# Output functions - write to Kafka, or to stdout as JSON

msgCount = 0

def emit(producer, topic, key, value_serializer, emitRecord):
    global msgCount
    # sid = emitRecord['sid']
    if producer is None:
        print(f'{key}|{json.dumps(emitRecord)}')
    else:
        producer.produce(topic, key=str(key), value=value_serializer(emitRecord, SerializationContext(topic, MessageField.VALUE)))
        msgCount += 1
        if msgCount >= 2000:
            producer.flush()
            msgCount = 0
        producer.poll(0)

def emitClick(p, t, vs, s):
    emitRecord = {
        'timestamp' : int(time.time()),
        'recordType' : 'click',
        'url' : s.url(),
        'useragent' : s.useragent,
        'statuscode' : selectAttr(d_statuscode),
        'state' : s.state,
        'statesVisited' : s.statesVisited, # cumulative state, ordered
        'sid' : s.sid,
        'uid' : s.uid,
        'isSubscriber' : s.isSubscriber,
        'campaign' : s.campaign,
        'channel' : s.channel,
        'contentId' : s.contentId,
        'subContentId' : s.subContentId,
        'gender' : s.gender,
        'age' : s.age,
        'latitude' : s.place[0],
        'longitude' : s.place[1],
        'place_name' : s.place[2],
        'country_code' : s.place[3],
        'timezone' : s.place[4]
    }
    emit(p, t, s.sid, vs, emitRecord)

def emitSession(p, t, vs, s):
    emitRecord = {
        'timestamp' : s.startTime,
        'recordType' : 'session',
        'useragent' : s.useragent,
        'statesVisited' : list(s.statesVisited), # cumulative state, unordered
        'sid' : s.sid,
        'uid' : s.uid,
        'isSubscriber' : s.isSubscriber,
        'campaign' : s.campaign,
        'channel' : s.channel,
        'gender' : s.gender,
        'age' : s.age,
        'latitude' : s.place[0],
        'longitude' : s.place[1],
        'place_name' : s.place[2],
        'country_code' : s.place[3],
        'timezone' : s.place[4]
    }
    # explode and pivot the states visited
    emitRecord.update( { t : (int(t in s.statesVisited)) for t in s.states } )
    emit(p, t, s.sid, vs, emitRecord)

def emitUser(p, t, vs, u):
    logging.debug(f'emitting user record {u}')
    emitRecord = {
        'timestamp' : u.updatedTime,
        'version' : u.version,
        'recordType' : 'user',
        'uid' : u.uid,
        'isSubscriber' : u.isSubscriber,
        'gender' : u.gender,
        'age' : u.age,
        'latitude' : u.place[0],
        'longitude' : u.place[1],
        'place_name' : u.place[2],
        'country_code' : u.place[3],
        'timezone' : u.place[4]
    }
    emit(p, t, u.uid, vs, emitRecord)

# Check configuration

def checkConfig(cfg):
    eps = 0.0001
    states = set(cfg['StateMachine']['States'])
    modes = cfg['StateMachine']['StateTransitionMatrix']
    logging.debug(f"Transition Matrix: {modes}")
    logging.debug(f"Transition Matrix: {modes.items()}")
    for mode in modes.keys():
        for originState, transitions in modes[mode].items():
            # is the origin state in the list?
            if originState not in states:
                logging.error(f'Mode {mode}: originState {originState} does not exist')
                raise GeneratorConfigError
            # do the target states match the main states list?
            if set(transitions.keys()) != states:
                logging.error(f'Mode {mode} originState {originState}: transitions do not match state list')
                raise GeneratorConfigError
            # are the probabilities okay?
            if abs(sum(transitions.values()) - 1.0) > eps:
                logging.error(f'Mode {mode} originState {originState}: transition probabilities do not add up to 1')
                raise GeneratorConfigError

# Read configuration

def readConfig(ifn):
    logging.debug(f'reading config file {ifn}')
    with open(ifn, 'r') as f:
        cfg = yaml.load(f, Loader=yaml.FullLoader)
        includecfgs = []
        # get include files if present
        for inc in cfg.get("IncludeOptional", []):
            try:
                logging.debug(f'reading include file {inc}')
                c = yaml.load(open(inc), Loader=yaml.FullLoader)
                includecfgs.append(c)
            except FileNotFoundError:
                logging.debug(f'optional include file {inc} not found, continuing')
        merge(cfg, *includecfgs)
        logging.info(f'Configuration: {cfg}')
        checkConfig(cfg)
        return cfg


# --- Main entry point ---

def main():

    global reconfigure

    # Install signal handlers

    # SIGHUP triggers a config reread
    signal.signal(signal.SIGHUP, hupHandler)

    # SIGUSR1 is used as a live check signal - ignore and just use the return code of kill(1) in the watchdog
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    # Parse command line arguments

    logLevel = logging.INFO
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', help='Enable debug logging', action='store_true')
    parser.add_argument('-q', '--quiet', help='Quiet mode (overrides Debug mode)', action='store_true')
    parser.add_argument('-f', '--config', help='Configuration file for session state machine(s)', required=True)
    # parser.add_argument('-m', '--mode', help='Mode for session state machine(s)', default='default')
    parser.add_argument('-n', '--dry-run', help='Write to stdout instead of Kafka',  action='store_true')
    args = parser.parse_args()

    if args.debug:
        logLevel = logging.DEBUG
    if args.quiet:
        logLevel = logging.ERROR

    logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logLevel)

    cfgfile = args.config

    sessionId = 0
    allSessions = []
    allUsers = {}

    while True:

        config = readConfig(cfgfile)
        allModes = config['ModeConfig'].keys()
        logging.debug(f'available modes: {allModes}')

        selector = config['Mode'] # this comes from the dynamic config now
        if selector is None or selector not in allModes:
            logging.debug('falling back to default mode')
            selector = 'default'

        if args.dry_run:
            producer = None
            clickTopic = None
            sessionTopic = None
            # userTopic = None
        else:
            clickTopic = config['General']['clickTopic']
            sessionTopic = config['General']['sessionTopic']
            # userTopic = config['General']['userTopic']
            logging.debug(f'clickTopic: {clickTopic} sessionTopic: {sessionTopic}')

            kafkaconf = config['Kafka']
            kafkaconf['client.id'] = socket.gethostname()
            logging.debug(f'Kafka client configuration: {kafkaconf}')
            producer = Producer(kafkaconf)

        clickSerializer = srSerializer(config, 'click')
        sessionSerializer = srSerializer(config, 'session')
        userSerializer = srSerializer(config, 'user')

        minSleep = config['General']['minSleep']
        if minSleep is None:
            minSleep = 0.01
        maxSleep = config['General']['maxSleep']
        if maxSleep is None:
            maxSleep = 0.04

        # a reconfigure may change the max sessions but does not touch existing ones
        maxSessions = config['General']['maxSessions']
        if maxSessions is None:
            maxSessions = 50000

        maxUsers = config['General']['maxUsers']
        userChangeProbability = config['General']['userChangeProbability']
        userMask = "u{:0>" + str(1 + math.floor(math.log10(maxUsers - 1))) + "}" # userMask.format(uidNum)
        logging.debug(f'user mask: {userMask}')

        timeEnvelope = config['ModeConfig'][selector]['timeEnvelope'] # array with 24 values
        # set up the spline interpolator
        xi = list(range(-24, 48)) # 3 times 24 hours, we are going to use only the [0, 24) part
        yi = timeEnvelope + timeEnvelope + timeEnvelope # 3 times the envelope so the middle part is stitched smoothly at the edges
        tck = interpolate.splrep(xi, yi)

        reconfigure = False

        while not reconfigure:

            logging.debug('Top of loop')
            logging.debug(f'Total elements in list: {len(allSessions)}')
            logging.debug(f'state selector: {selector}')
            # With a certain probability, create a new session
            if random.random() < 0.5 and len(allSessions) < maxSessions:
                sessionId += 1
                logging.debug(f'--> Creating Session: id {sessionId}')
                salesAmount = random.uniform(10.0, 90.0);

                # Pick the right transition matrix for the mode we are running in
                States = config['StateMachine']['States']
                StateTransitionMatrix = config['StateMachine']['StateTransitionMatrix'][selector]

                uid = userMask.format(fake.random_int(min=0, max=maxUsers-1))
                if uid not in allUsers:
                    newPlace = fake.location_on_land()
                    newUser = User( 
                        updatedTime = int(time.time()),
                        version = 1,
                        recordType = 'user',
                        uid = uid,
                        isSubscriber = int(fake.boolean(chance_of_getting_true=5)),
                        gender = selectAttr(config['ModeConfig'][selector]['gender']),
                        age = selectAttr(config['ModeConfig'][selector]['age']),
                        place = fake.location_on_land()
                    )
                    logging.debug(f'new user: {newUser}')
                    # emitUser(producer, userTopic, userSerializer, newUser)
                    allUsers[uid] = newUser
                elif random.random() < userChangeProbability:
                    # address change
                    logging.debug(f'user {uid} changed address')
                    allUsers[uid].version += 1
                    allUsers[uid].place = fake.location_on_land()
                    # emitUser(producer, userTopic, userSerializer, allUsers[uid])

                # The new session will start on the home page and it will be assigned a random user ID
                newSession = Session(
                    States, States[0], StateTransitionMatrix,
                    useragent = fake.user_agent(),
                    sid = sessionId,
                    uid = uid, # 10000..99999
                    isSubscriber = allUsers[uid].isSubscriber,
                    campaign = selectAttr(config['ModeConfig'][selector]['campaign']),
                    channel = selectAttr(config['ModeConfig'][selector]['channel']),
                    contentId = random.choice(l_content),
                    subContentId = fake.sentence(nb_words=6)[:-1],
                    gender = allUsers[uid].gender,
                    age = allUsers[uid].age,
                    place = allUsers[uid].place
                )
                emitClick(producer, clickTopic, clickSerializer, newSession)
                if not args.quiet:
                    sys.stderr.write('.')
                    sys.stderr.flush()
                allSessions.append(newSession)
            # Pick one of the sessions
            try:
                thisSession = random.choice(allSessions)
                logging.debug(f'--> Session id {thisSession.sid}')
                logging.debug(thisSession)
                thisSession.advance()
                emitClick(producer, clickTopic, clickSerializer, thisSession)
                if not args.quiet:
                    sys.stderr.write('.')
                    sys.stderr.flush()
            except IndexError:
                logging.debug('--> No sessions to choose from')
            except KeyError:
                emitSession(producer, sessionTopic, sessionSerializer, thisSession)
                if not args.quiet:
                    sys.stderr.write(':')
                    sys.stderr.flush()
                # Here we end up when the session was in exit state
                logging.debug(f'--> removing session id {thisSession.sid}')
                allSessions.remove(thisSession)
            tm = time.gmtime()
            # code for linear interpolation
            # weight = (timeEnvelope[(tm.tm_hour + 1) % 24] * tm.tm_min + timeEnvelope[tm.tm_hour] * (60 - tm.tm_min)) / 60.0 # this should be between 0 and 1000
            # but use spline instead:
            weight = interpolate.splev(tm.tm_hour + tm.tm_min / 60.0 + tm.tm_sec / 3600.0, tck)
            logging.debug(f'envelope values: {timeEnvelope[tm.tm_hour]}, {timeEnvelope[(tm.tm_hour + 1) % 24]}')
            logging.debug(f'weight from envelope: {weight}')
            waitSecs = random.uniform(minSleep, maxSleep) 
            if weight > 0:
                waitSecs = waitSecs * 1000.0 / weight
            logging.debug(f'wait time: {waitSecs}')
            time.sleep(waitSecs)
        

if __name__ == "__main__":
    main()
