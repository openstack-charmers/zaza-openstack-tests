# Copyright 2018 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Collection of utilities to support zaza tests etc."""


import enum
import time

import zaza.charm_lifecycle.utils

from keystoneauth1.exceptions.base import ClientException
from keystoneauth1.exceptions.connection import ConnectFailure
from keystoneauth1.exceptions.connection import RetriableConnectionFailure


class ObjectRetrierWraps(object):
    """An automatic retrier for an object.

    This is designed to be used with an instance of an object.  Basically, it
    wraps the object and any attributes that are fetched.  Essentially, it is
    used to provide retries on method calls on openstack client objects in
    tests to increase robustness of tests.

    Although, technically this is bad, retries can be logged with the optional
    log method.

    Usage:

        # get a client that does 3 retries, waits 5 seconds between retries and
        # retries on any error.
        some_client = ObjectRetrierWraps(get_some_client)
        # this gets retried up to 3 times.
        things = some_client.list_things()

    Note, it is quite simple.  It wraps the object and on a getattr(obj, name)
    it finds the name and then returns a wrapped version of that name.  On a
    call, it returns the value of that call.  It only wraps objects in the
    chain that are either callable or have a __getattr__() method.  i.e. one
    that can then be retried or further fetched.  This means that if a.b.c() is
    a chain of objects, and we just wrap 'a', then 'b' and 'c' will both be
    wrapped that the 'c' object __call__() method will be the one that is
    actually retried.

    Note: this means that properties that do method calls won't be retried.
    This is a limitation that may be addressed in the future, if it is needed.
    """

    def __init__(self, obj, num_retries=3, initial_interval=5.0, backoff=1.0,
                 max_interval=15.0, total_wait=30.0, retry_exceptions=None,
                 log=None):
        """Initialise the retrier object.

        :param obj: The object to wrap. Ought to be an instance of something
            that you want to get methods on to call or be called itself.
        :type obj: Any
        :param num_retries: The (maximum) number of retries.  May not be hit if
            the total_wait time is exceeded.
        :type num_retries: int
        :param initial_interval: The initial or starting interval between
            retries.
        :type initial_interval: float
        :param backoff: The exponential backoff multiple.  1 is linear.
        :type backoff: float
        :param max_interval: The maximum interval between retries.
            If backoff is >1 then the initial_interval will never grow larger
            than max_interval.
        :type max_interval: float
        :param retry_exceptions: The list of exceptions to retry on, or None.
            If a list, then it will only retry if the exception is one of the
            ones in the list.
        :type retry_exceptions: List[Exception]
        """
        # Note we use semi-private variable names that shouldn't clash with any
        # on the actual object.
        self.__obj = obj
        self.__kwargs = {
            'num_retries': num_retries,
            'initial_interval': initial_interval,
            'backoff': backoff,
            'max_interval': max_interval,
            'total_wait': total_wait,
            'retry_exceptions': retry_exceptions,
            'log': log or (lambda x: None),
        }

    def __getattr__(self, name):
        """Get attribute; delegates to wrapped object."""
        # Note the above may generate an attribute error; we expect this and
        # will fail with an attribute error.
        attr = getattr(self.__obj, name)
        if callable(attr) or hasattr(attr, "__getattr__"):
            return ObjectRetrierWraps(attr, **self.__kwargs)
        else:
            return attr
        # TODO(ajkavanagh): Note detecting a property is a bit trickier.  we
        # can do isinstance(attr, property), but then the act of accessing it
        # is what calls it.  i.e. it would fail at the getattr(self.__obj,
        # name) stage.  The solution is to check first, and if it's a property,
        # then treat it like the retrier.  However, I think this is too
        # complex for the first go, and to use manual retries in that instance.

    def __call__(self, *args, **kwargs):
        """Call the object; delegates to the wrapped object."""
        obj = self.__obj
        retry = 0
        wait = self.__kwargs['initial_interval']
        max_interval = self.__kwargs['max_interval']
        log = self.__kwargs['log']
        backoff = self.__kwargs['backoff']
        total_wait = self.__kwargs['total_wait']
        num_retries = self.__kwargs['num_retries']
        retry_exceptions = self.__kwargs['retry_exceptions']
        wait_so_far = 0
        while True:
            try:
                return obj(*args, **kwargs)
            except Exception as e:
                # if retry_exceptions is not None, or the type of the exception
                # is not in the list of retries, then raise an exception
                # immediately.  This means that if retry_exceptions is None,
                # then the method is always retried.
                if (retry_exceptions is not None and
                        type(e) not in retry_exceptions):
                    raise
                retry += 1
                if retry > num_retries:
                    log("{}: exceeded number of retries, so erroring out"
                        .format(str(obj)))
                    raise e
                log("{}: call failed: retrying in {} seconds"
                    .format(str(obj), wait))
                time.sleep(wait)
                wait_so_far += wait
                if wait_so_far >= total_wait:
                    raise e
                wait = wait * backoff
                if wait > max_interval:
                    wait = max_interval


def retry_on_connect_failure(client, **kwargs):
    """Retry an object that eventually gets resolved to a call.

    Specifically, this uses ObjectRetrierWraps but only against the
    keystoneauth1.exceptions.connection.ConnectFailure exeception.

    :params client: the object that may throw and exception when called.
    :type client: Any
    :params **kwargs: the arguments supplied to the ObjectRetrierWraps init
                      method
    :type **kwargs: Dict[Any]
    :returns: client wrapped in an ObjectRetrierWraps instance
    :rtype: ObjectRetrierWraps[client]
    """
    kwcopy = kwargs.copy()
    if 'retry_exceptions' not in kwcopy:
        kwcopy['retry_exceptions'] = []
    if ConnectFailure not in kwcopy['retry_exceptions']:
        kwcopy['retry_exceptions'].append(ConnectFailure)
    return ObjectRetrierWraps(client, **kwcopy)


TEST_CONFIG_ACCEPTANCE_LEVEL_KEY = 'acceptance_level'


class AcceptanceLevel(str, enum.Enum):
    """Enum describing available acceptance level options."""

    LENIENT = 'lenient'
    PERMISSIVE = 'permissive'
    STRICT = 'strict'


def get_acceptance_level():
    """Retrieve acceptance level from charm config.

    :returns: Configured or default acceptance level.
    :rtype: AcceptanceLevel
    """
    level = AcceptanceLevel.STRICT
    config_level = zaza.charm_lifecycle.utils.get_charm_config(
        fatal=False).get(TEST_CONFIG_ACCEPTANCE_LEVEL_KEY, level)

    if config_level == AcceptanceLevel.PERMISSIVE:
        level = AcceptanceLevel.PERMISSIVE
    elif config_level == AcceptanceLevel.LENIENT:
        level = AcceptanceLevel.LENIENT

    return level


def retry_to_configured_acceptance_level(client, **kwargs):
    """Retry an object that eventually gets resolved to a call.

    Specifically, this uses ObjectRetrierWraps, but only against the
    exceptions listed towards the configured acceptance level.

    :params client: the object that may throw and exception when called.
    :type client: Any
    :params **kwargs: the arguments supplied to the ObjectRetrierWraps init
                      method
    :type **kwargs: Dict[Any]
    :returns: client wrapped in an ObjectRetrierWraps instance
    :rtype: ObjectRetrierWraps[client]
    """
    kwcopy = kwargs.copy()
    if 'retry_exceptions' not in kwcopy:
        kwcopy['retry_exceptions'] = []

    acceptance_level = get_acceptance_level()
    if acceptance_level == AcceptanceLevel.PERMISSIVE:
        kwcopy['retry_exceptions'].append(RetriableConnectionFailure)
    elif acceptance_level == AcceptanceLevel.LENIENT:
        kwcopy['retry_exceptions'].append(ClientException)

    return ObjectRetrierWraps(client, **kwcopy)
