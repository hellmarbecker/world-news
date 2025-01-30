#!/bin/bash

BASE=~/world-news
PIDFILE=/tmp/news_simulator.pid

LOG=/tmp/news_simulator.log
ERROR=/tmp/news_simulator-error.log
CONFIG=news_config.yml
CONFIG_DYNAMIC=news_dynamic.yml
CMD=news_process.py
# CMD=dummy.py
OPTSTRING="dnq" # recognized cmd options

setProfile() {
    # only write profile file
    mode=${1:-"default"}
    echo "==== Set Profile: ${mode}"
    echo "Mode: ${mode}" >"${BASE}/${CONFIG_DYNAMIC}"
}

status() {
    # return 0 if running
    signal=${1:-"USR1"}
    echo "==== Status check with signal $signal"
    if [ -f $PIDFILE ]
    then
        PID=$( cat $PIDFILE )
        echo
        echo "Found PID: [$PID]"
        kill -$signal $PID
        alive=$?
        echo "Live check: $alive"
        # we are running, nothing to do
        [ $alive -eq 0 ] && return 0

        # if we get here, we have a stale PID file
        /bin/rm -f $PIDFILE
    fi 
    return 1
}

reload() {
    # only reload, do not set profile file
    echo "==== Reload"
    status "HUP"
    ret=$?
    echo "status returns $ret"
    return $ret
}

start() {
    # set profile file, if parameter given
    [  -z $1 ] || setProfile $1

    # restart if necessary, otherwise reload config
    # Check if we are already running
    status "HUP" && return 0

    echo "==== Starting"
    if nohup $COMMAND >>$LOG 2>&1 &
    then
        echo $! >$PIDFILE
        echo "Done."
        echo "$(date '+%Y-%m-%d %X'): START" >>$LOG
        return 0
    fi 

    echo "Error... "
    /bin/rm -f $PIDFILE
    return 1
}

stop() {
    echo "==== Stop"

    if [ -f $PIDFILE ]
    then
        if kill $( cat $PIDFILE )
        then echo "Done."
             echo "$(date '+%Y-%m-%d %X'): STOP" >>$LOG
        fi
        /bin/rm -f $PIDFILE
    else
        echo "No pid file. Already stopped?"
    fi
}

# --- main entry point ---

while getopts ${OPTSTRING} arg; do
    case "${arg}" in
        d|n|q)
            FLAGS="${FLAGS} -${arg}"
            echo "Flags: ${FLAGS}"
            ;;
        *)
            echo "Unknown option: -${OPTARG}"
            exit 2
            ;;
    esac 
done
# if no flags are given, start in quiet mode
FLAGS=${FLAGS:-"-q"}
echo "Flags: ${FLAGS}"
shift $((OPTIND -1))

profile=$2
COMMAND="python3 $BASE/$CMD $FLAGS -f $BASE/$CONFIG"
echo "remaining parameters: $@"
# exit 0

case "$1" in
    'start')
            start "${profile}"
            ;;
    'stop')
            stop
            ;;
    'restart')
            stop
            echo "Sleeping..."
            sleep 1
            start "${profile}"
            ;;
    'status')
            status
            ;;
    'switch')
            start "${profile}"
            ;;
    *)
            echo
            echo "Usage: $0 [-dnq] { start | stop | restart | status | switch } <profile>"
            echo
            exit 1
            ;;
esac

exit 0

