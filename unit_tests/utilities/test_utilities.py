# Copyright 2021 Canonical Ltd.
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

import mock

import unit_tests.utils as ut_utils

import zaza.openstack.utilities as utilities


class SomeException(Exception):
    pass


class SomeException2(Exception):
    pass


class SomeException3(Exception):
    pass


class TestObjectRetrierWraps(ut_utils.BaseTestCase):

    def test_object_wrap(self):

        class A:

            def func(self, a, b=1):
                return a + b

        a = A()
        wrapped_a = utilities.ObjectRetrierWraps(a)
        self.assertEqual(wrapped_a.func(3), 4)

    def test_object_multilevel_wrap(self):

        class A:

            def f1(self, a, b):
                return a * b

        class B:

            @property
            def f2(self):

                return A()

        b = B()
        wrapped_b = utilities.ObjectRetrierWraps(b)
        self.assertEqual(wrapped_b.f2.f1(5, 6), 30)

    def test_object_wrap_number(self):

        class A:

            class_a = 5

            def __init__(self):
                self.instance_a = 10

            def f1(self, a, b):
                return a * b

        a = A()
        wrapped_a = utilities.ObjectRetrierWraps(a)
        self.assertEqual(wrapped_a.class_a, 5)
        self.assertEqual(wrapped_a.instance_a, 10)

    @mock.patch("time.sleep")
    def test_object_wrap_exception(self, mock_sleep):

        class A:

            def func(self):
                raise SomeException()

        a = A()
        # retry on a specific exception
        wrapped_a = utilities.ObjectRetrierWraps(
            a, num_retries=1, retry_exceptions=[SomeException])
        with self.assertRaises(SomeException):
            wrapped_a.func()

        mock_sleep.assert_called_once_with(5)

        # also retry on any exception if none specified
        wrapped_a = utilities.ObjectRetrierWraps(a, num_retries=1)
        mock_sleep.reset_mock()
        with self.assertRaises(SomeException):
            wrapped_a.func()

        mock_sleep.assert_called_once_with(5)

        # no retry if exception isn't listed.
        wrapped_a = utilities.ObjectRetrierWraps(
            a, num_retries=1, retry_exceptions=[SomeException2])
        mock_sleep.reset_mock()
        with self.assertRaises(SomeException):
            wrapped_a.func()

        mock_sleep.assert_not_called()

    @mock.patch("time.sleep")
    def test_object_wrap_multilevel_with_exception(self, mock_sleep):

        class A:

            def func(self):
                raise SomeException()

        class B:

            def __init__(self):
                self.a = A()

        b = B()
        # retry on a specific exception
        wrapped_b = utilities.ObjectRetrierWraps(
            b, num_retries=1, retry_exceptions=[SomeException])
        with self.assertRaises(SomeException):
            wrapped_b.a.func()

        mock_sleep.assert_called_once_with(5)

    @mock.patch("time.sleep")
    def test_log_called(self, mock_sleep):

        class A:

            def func(self):
                raise SomeException()

        a = A()
        mock_log = mock.Mock()
        wrapped_a = utilities.ObjectRetrierWraps(
            a, num_retries=1, log=mock_log)
        with self.assertRaises(SomeException):
            wrapped_a.func()

        # there should be two calls; one for the single retry and one for the
        # failure.
        self.assertEqual(mock_log.call_count, 6)

    @mock.patch("time.sleep")
    def test_back_off_maximum(self, mock_sleep):

        class A:

            def func(self):
                raise SomeException()

        a = A()
        wrapped_a = utilities.ObjectRetrierWraps(a, num_retries=3, backoff=2)
        with self.assertRaises(SomeException):
            wrapped_a.func()
        # Note third call hits maximum wait time of 15.
        mock_sleep.assert_has_calls([mock.call(5),
                                     mock.call(10),
                                     mock.call(15)])

    @mock.patch("time.sleep")
    def test_total_wait(self, mock_sleep):

        class A:

            def func(self):
                raise SomeException()

        a = A()
        wrapped_a = utilities.ObjectRetrierWraps(
            a, num_retries=3, total_wait=9)
        with self.assertRaises(SomeException):
            wrapped_a.func()
        # Note only two calls, as total wait is 9, so a 3rd retry would exceed
        # that.
        mock_sleep.assert_has_calls([mock.call(5),
                                     mock.call(5)])

    @mock.patch("time.sleep")
    def test_retry_on_connect_failure(self, mock_sleep):

        class A:

            def func1(self):
                raise SomeException()

            def func2(self):
                raise utilities.ConnectFailure()

        a = A()
        wrapped_a = utilities.retry_on_connect_failure(a, num_retries=2)
        with self.assertRaises(SomeException):
            wrapped_a.func1()
        mock_sleep.assert_not_called()
        with self.assertRaises(utilities.ConnectFailure):
            wrapped_a.func2()
        mock_sleep.assert_has_calls([mock.call(5)])
