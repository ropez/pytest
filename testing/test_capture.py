# note: py.io capture tests where copied from
# pylib 1.4.20.dev2 (rev 13d9af95547e)
from __future__ import with_statement
import os
import sys
import py
import pytest
import contextlib

from _pytest import capture
from _pytest.capture import CaptureManager
from py.builtin import print_

needsosdup = pytest.mark.xfail("not hasattr(os, 'dup')")

if sys.version_info >= (3, 0):
    def tobytes(obj):
        if isinstance(obj, str):
            obj = obj.encode('UTF-8')
        assert isinstance(obj, bytes)
        return obj

    def totext(obj):
        if isinstance(obj, bytes):
            obj = str(obj, 'UTF-8')
        assert isinstance(obj, str)
        return obj
else:
    def tobytes(obj):
        if isinstance(obj, unicode):
            obj = obj.encode('UTF-8')
        assert isinstance(obj, str)
        return obj

    def totext(obj):
        if isinstance(obj, str):
            obj = unicode(obj, 'UTF-8')
        assert isinstance(obj, unicode)
        return obj


def oswritebytes(fd, obj):
    os.write(fd, tobytes(obj))



class TestCaptureManager:
    def test_getmethod_default_no_fd(self, testdir, monkeypatch):
        config = testdir.parseconfig(testdir.tmpdir)
        assert config.getvalue("capture") is None
        capman = CaptureManager()
        monkeypatch.delattr(os, 'dup', raising=False)
        try:
            assert capman._getmethod(config, None) == "sys"
        finally:
            monkeypatch.undo()

    @pytest.mark.parametrize("mode", "no fd sys".split())
    def test_configure_per_fspath(self, testdir, mode):
        config = testdir.parseconfig(testdir.tmpdir)
        capman = CaptureManager()
        hasfd = hasattr(os, 'dup')
        if hasfd:
            assert capman._getmethod(config, None) == "fd"
        else:
            assert capman._getmethod(config, None) == "sys"

        if not hasfd and mode == 'fd':
            return
        sub = testdir.tmpdir.mkdir("dir" + mode)
        sub.ensure("__init__.py")
        sub.join("conftest.py").write('option_capture = %r' % mode)
        assert capman._getmethod(config, sub.join("test_hello.py")) == mode

    @needsosdup
    @pytest.mark.parametrize("method", ['no', 'fd', 'sys'])
    def test_capturing_basic_api(self, method):
        capouter = capture.StdCaptureFD()
        old = sys.stdout, sys.stderr, sys.stdin
        try:
            capman = CaptureManager()
            # call suspend without resume or start
            outerr = capman.suspendcapture()
            outerr = capman.suspendcapture()
            assert outerr == ("", "")
            capman.resumecapture(method)
            print ("hello")
            out, err = capman.suspendcapture()
            if method == "no":
                assert old == (sys.stdout, sys.stderr, sys.stdin)
            else:
                assert out == "hello\n"
            capman.resumecapture(method)
            out, err = capman.suspendcapture()
            assert not out and not err
            capman.reset_capturings()
        finally:
            capouter.reset()

    @needsosdup
    def test_juggle_capturings(self, testdir):
        capouter = capture.StdCaptureFD()
        try:
            #config = testdir.parseconfig(testdir.tmpdir)
            capman = CaptureManager()
            try:
                capman.resumecapture("fd")
                pytest.raises(ValueError, 'capman.resumecapture("fd")')
                pytest.raises(ValueError, 'capman.resumecapture("sys")')
                os.write(1, "hello\n".encode('ascii'))
                out, err = capman.suspendcapture()
                assert out == "hello\n"
                capman.resumecapture("sys")
                os.write(1, "hello\n".encode('ascii'))
                py.builtin.print_("world", file=sys.stderr)
                out, err = capman.suspendcapture()
                assert not out
                assert err == "world\n"
            finally:
                capman.reset_capturings()
        finally:
            capouter.reset()


@pytest.mark.parametrize("method", ['fd', 'sys'])
def test_capturing_unicode(testdir, method):
    if hasattr(sys, "pypy_version_info") and sys.pypy_version_info < (2,2):
        pytest.xfail("does not work on pypy < 2.2")
    if sys.version_info >= (3, 0):
        obj = "'b\u00f6y'"
    else:
        obj = "u'\u00f6y'"
    testdir.makepyfile("""
        # coding=utf8
        # taken from issue 227 from nosetests
        def test_unicode():
            import sys
            print (sys.stdout)
            print (%s)
    """ % obj)
    result = testdir.runpytest("--capture=%s" % method)
    result.stdout.fnmatch_lines([
        "*1 passed*"
    ])


@pytest.mark.parametrize("method", ['fd', 'sys'])
def test_capturing_bytes_in_utf8_encoding(testdir, method):
    testdir.makepyfile("""
        def test_unicode():
            print ('b\\u00f6y')
    """)
    result = testdir.runpytest("--capture=%s" % method)
    result.stdout.fnmatch_lines([
        "*1 passed*"
    ])


def test_collect_capturing(testdir):
    p = testdir.makepyfile("""
        print ("collect %s failure" % 13)
        import xyz42123
    """)
    result = testdir.runpytest(p)
    result.stdout.fnmatch_lines([
        "*Captured stdout*",
        "*collect 13 failure*",
    ])


class TestPerTestCapturing:
    def test_capture_and_fixtures(self, testdir):
        p = testdir.makepyfile("""
            def setup_module(mod):
                print ("setup module")
            def setup_function(function):
                print ("setup " + function.__name__)
            def test_func1():
                print ("in func1")
                assert 0
            def test_func2():
                print ("in func2")
                assert 0
        """)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            "setup module*",
            "setup test_func1*",
            "in func1*",
            "setup test_func2*",
            "in func2*",
        ])

    @pytest.mark.xfail
    def test_capture_scope_cache(self, testdir):
        p = testdir.makepyfile("""
            import sys
            def setup_module(func):
                print ("module-setup")
            def setup_function(func):
                print ("function-setup")
            def test_func():
                print ("in function")
                assert 0
            def teardown_function(func):
                print ("in teardown")
        """)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            "*test_func():*",
            "*Captured stdout during setup*",
            "module-setup*",
            "function-setup*",
            "*Captured stdout*",
            "in teardown*",
        ])

    def test_no_carry_over(self, testdir):
        p = testdir.makepyfile("""
            def test_func1():
                print ("in func1")
            def test_func2():
                print ("in func2")
                assert 0
        """)
        result = testdir.runpytest(p)
        s = result.stdout.str()
        assert "in func1" not in s
        assert "in func2" in s

    def test_teardown_capturing(self, testdir):
        p = testdir.makepyfile("""
            def setup_function(function):
                print ("setup func1")
            def teardown_function(function):
                print ("teardown func1")
                assert 0
            def test_func1():
                print ("in func1")
                pass
        """)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            '*teardown_function*',
            '*Captured stdout*',
            "setup func1*",
            "in func1*",
            "teardown func1*",
            #"*1 fixture failure*"
        ])

    def test_teardown_capturing_final(self, testdir):
        p = testdir.makepyfile("""
            def teardown_module(mod):
                print ("teardown module")
                assert 0
            def test_func():
                pass
        """)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            "*def teardown_module(mod):*",
            "*Captured stdout*",
            "*teardown module*",
            "*1 error*",
        ])

    def test_capturing_outerr(self, testdir):
        p1 = testdir.makepyfile("""
            import sys
            def test_capturing():
                print (42)
                sys.stderr.write(str(23))
            def test_capturing_error():
                print (1)
                sys.stderr.write(str(2))
                raise ValueError
        """)
        result = testdir.runpytest(p1)
        result.stdout.fnmatch_lines([
            "*test_capturing_outerr.py .F",
            "====* FAILURES *====",
            "____*____",
            "*test_capturing_outerr.py:8: ValueError",
            "*--- Captured stdout ---*",
            "1",
            "*--- Captured stderr ---*",
            "2",
        ])


class TestLoggingInteraction:
    def test_logging_stream_ownership(self, testdir):
        p = testdir.makepyfile("""
            def test_logging():
                import logging
                import pytest
                stream = capture.TextIO()
                logging.basicConfig(stream=stream)
                stream.close() # to free memory/release resources
        """)
        result = testdir.runpytest(p)
        result.stderr.str().find("atexit") == -1

    def test_logging_and_immediate_setupteardown(self, testdir):
        p = testdir.makepyfile("""
            import logging
            def setup_function(function):
                logging.warn("hello1")

            def test_logging():
                logging.warn("hello2")
                assert 0

            def teardown_function(function):
                logging.warn("hello3")
                assert 0
        """)
        for optargs in (('--capture=sys',), ('--capture=fd',)):
            print (optargs)
            result = testdir.runpytest(p, *optargs)
            s = result.stdout.str()
            result.stdout.fnmatch_lines([
                "*WARN*hello3",  # errors show first!
                "*WARN*hello1",
                "*WARN*hello2",
            ])
            # verify proper termination
            assert "closed" not in s

    def test_logging_and_crossscope_fixtures(self, testdir):
        p = testdir.makepyfile("""
            import logging
            def setup_module(function):
                logging.warn("hello1")

            def test_logging():
                logging.warn("hello2")
                assert 0

            def teardown_module(function):
                logging.warn("hello3")
                assert 0
        """)
        for optargs in (('--capture=sys',), ('--capture=fd',)):
            print (optargs)
            result = testdir.runpytest(p, *optargs)
            s = result.stdout.str()
            result.stdout.fnmatch_lines([
                "*WARN*hello3",  # errors come first
                "*WARN*hello1",
                "*WARN*hello2",
            ])
            # verify proper termination
            assert "closed" not in s

    def test_logging_initialized_in_test(self, testdir):
        p = testdir.makepyfile("""
            import sys
            def test_something():
                # pytest does not import logging
                assert 'logging' not in sys.modules
                import logging
                logging.basicConfig()
                logging.warn("hello432")
                assert 0
        """)
        result = testdir.runpytest(
            p, "--traceconfig",
            "-p", "no:capturelog")
        assert result.ret != 0
        result.stdout.fnmatch_lines([
            "*hello432*",
        ])
        assert 'operation on closed file' not in result.stderr.str()

    def test_conftestlogging_is_shown(self, testdir):
        testdir.makeconftest("""
                import logging
                logging.basicConfig()
                logging.warn("hello435")
        """)
        # make sure that logging is still captured in tests
        result = testdir.runpytest("-s", "-p", "no:capturelog")
        assert result.ret == 0
        result.stderr.fnmatch_lines([
            "WARNING*hello435*",
        ])
        assert 'operation on closed file' not in result.stderr.str()

    def test_conftestlogging_and_test_logging(self, testdir):
        testdir.makeconftest("""
                import logging
                logging.basicConfig()
        """)
        # make sure that logging is still captured in tests
        p = testdir.makepyfile("""
            def test_hello():
                import logging
                logging.warn("hello433")
                assert 0
        """)
        result = testdir.runpytest(p, "-p", "no:capturelog")
        assert result.ret != 0
        result.stdout.fnmatch_lines([
            "WARNING*hello433*",
        ])
        assert 'something' not in result.stderr.str()
        assert 'operation on closed file' not in result.stderr.str()


class TestCaptureFixture:
    def test_std_functional(self, testdir):
        reprec = testdir.inline_runsource("""
            def test_hello(capsys):
                print (42)
                out, err = capsys.readouterr()
                assert out.startswith("42")
        """)
        reprec.assertoutcome(passed=1)

    def test_capsyscapfd(self, testdir):
        p = testdir.makepyfile("""
            def test_one(capsys, capfd):
                pass
            def test_two(capfd, capsys):
                pass
        """)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            "*ERROR*setup*test_one*",
            "*capsys*capfd*same*time*",
            "*ERROR*setup*test_two*",
            "*capsys*capfd*same*time*",
            "*2 error*"])

    @pytest.mark.parametrize("method", ["sys", "fd"])
    def test_capture_is_represented_on_failure_issue128(self, testdir, method):
        p = testdir.makepyfile("""
            def test_hello(cap%s):
                print ("xxx42xxx")
                assert 0
        """ % method)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            "xxx42xxx",
        ])

    @needsosdup
    def test_stdfd_functional(self, testdir):
        reprec = testdir.inline_runsource("""
            def test_hello(capfd):
                import os
                os.write(1, "42".encode('ascii'))
                out, err = capfd.readouterr()
                assert out.startswith("42")
                capfd.close()
        """)
        reprec.assertoutcome(passed=1)

    def test_partial_setup_failure(self, testdir):
        p = testdir.makepyfile("""
            def test_hello(capsys, missingarg):
                pass
        """)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            "*test_partial_setup_failure*",
            "*1 error*",
        ])

    @needsosdup
    def test_keyboardinterrupt_disables_capturing(self, testdir):
        p = testdir.makepyfile("""
            def test_hello(capfd):
                import os
                os.write(1, str(42).encode('ascii'))
                raise KeyboardInterrupt()
        """)
        result = testdir.runpytest(p)
        result.stdout.fnmatch_lines([
            "*KeyboardInterrupt*"
        ])
        assert result.ret == 2

    @pytest.mark.issue14
    def test_capture_and_logging(self, testdir):
        p = testdir.makepyfile("""
            import logging
            def test_log(capsys):
                logging.error('x')
            """)
        result = testdir.runpytest(p)
        assert 'closed' not in result.stderr.str()


def test_setup_failure_does_not_kill_capturing(testdir):
    sub1 = testdir.mkpydir("sub1")
    sub1.join("conftest.py").write(py.code.Source("""
        def pytest_runtest_setup(item):
            raise ValueError(42)
    """))
    sub1.join("test_mod.py").write("def test_func1(): pass")
    result = testdir.runpytest(testdir.tmpdir, '--traceconfig')
    result.stdout.fnmatch_lines([
        "*ValueError(42)*",
        "*1 error*"
    ])


def test_fdfuncarg_skips_on_no_osdup(testdir):
    testdir.makepyfile("""
        import os
        if hasattr(os, 'dup'):
            del os.dup
        def test_hello(capfd):
            pass
    """)
    result = testdir.runpytest("--capture=no")
    result.stdout.fnmatch_lines([
        "*1 skipped*"
    ])


def test_capture_conftest_runtest_setup(testdir):
    testdir.makeconftest("""
        def pytest_runtest_setup():
            print ("hello19")
    """)
    testdir.makepyfile("def test_func(): pass")
    result = testdir.runpytest()
    assert result.ret == 0
    assert 'hello19' not in result.stdout.str()


def test_capture_early_option_parsing(testdir):
    testdir.makeconftest("""
        def pytest_runtest_setup():
            print ("hello19")
    """)
    testdir.makepyfile("def test_func(): pass")
    result = testdir.runpytest("-vs")
    assert result.ret == 0
    assert 'hello19' in result.stdout.str()


@pytest.mark.xfail(sys.version_info >= (3, 0), reason='encoding issues')
@pytest.mark.xfail(sys.version_info < (2, 6), reason='test not run on py25')
def test_capture_binary_output(testdir):
    testdir.makepyfile(r"""
        import pytest

        def test_a():
            import sys
            import subprocess
            subprocess.call([sys.executable, __file__])

        @pytest.mark.skip
        def test_foo():
            import os;os.write(1, b'\xc3')

        if __name__ == '__main__':
            test_foo()
        """)
    result = testdir.runpytest('--assert=plain')
    result.stdout.fnmatch_lines([
        '*2 passed*',
    ])


class TestTextIO:
    def test_text(self):
        f = capture.TextIO()
        f.write("hello")
        s = f.getvalue()
        assert s == "hello"
        f.close()

    def test_unicode_and_str_mixture(self):
        f = capture.TextIO()
        if sys.version_info >= (3, 0):
            f.write("\u00f6")
            pytest.raises(TypeError, "f.write(bytes('hello', 'UTF-8'))")
        else:
            f.write(unicode("\u00f6", 'UTF-8'))
            f.write("hello")  # bytes
            s = f.getvalue()
            f.close()
            assert isinstance(s, unicode)


def test_bytes_io():
    f = capture.BytesIO()
    f.write(tobytes("hello"))
    pytest.raises(TypeError, "f.write(totext('hello'))")
    s = f.getvalue()
    assert s == tobytes("hello")


def test_dontreadfrominput():
    from _pytest.capture import DontReadFromInput
    f = DontReadFromInput()
    assert not f.isatty()
    pytest.raises(IOError, f.read)
    pytest.raises(IOError, f.readlines)
    pytest.raises(IOError, iter, f)
    pytest.raises(ValueError, f.fileno)
    f.close()  # just for completeness


@pytest.yield_fixture
def tmpfile(testdir):
    f = testdir.makepyfile("").open('wb+')
    yield f
    if not f.closed:
        f.close()

@needsosdup
def test_dupfile(tmpfile):
    flist = []
    for i in range(5):
        nf = capture.dupfile(tmpfile, encoding="utf-8")
        assert nf != tmpfile
        assert nf.fileno() != tmpfile.fileno()
        assert nf not in flist
        print_(i, end="", file=nf)
        flist.append(nf)
    for i in range(5):
        f = flist[i]
        f.close()
    tmpfile.seek(0)
    s = tmpfile.read()
    assert "01234" in repr(s)
    tmpfile.close()


def test_dupfile_no_mode():
    """
    dupfile should trap an AttributeError and return f if no mode is supplied.
    """
    class SomeFileWrapper(object):
        "An object with a fileno method but no mode attribute"
        def fileno(self):
            return 1
    tmpfile = SomeFileWrapper()
    assert capture.dupfile(tmpfile) is tmpfile
    with pytest.raises(AttributeError):
        capture.dupfile(tmpfile, raising=True)


@contextlib.contextmanager
def lsof_check():
    pid = os.getpid()
    try:
        out = py.process.cmdexec("lsof -p %d" % pid)
    except py.process.cmdexec.Error:
        pytest.skip("could not run 'lsof'")
    yield
    out2 = py.process.cmdexec("lsof -p %d" % pid)
    len1 = len([x for x in out.split("\n") if "REG" in x])
    len2 = len([x for x in out2.split("\n") if "REG" in x])
    assert len2 < len1 + 3, out2


class TestFDCapture:
    pytestmark = needsosdup

    def test_simple(self, tmpfile):
        fd = tmpfile.fileno()
        cap = capture.FDCapture(fd)
        data = tobytes("hello")
        os.write(fd, data)
        f = cap.done()
        s = f.read()
        f.close()
        assert not s
        cap = capture.FDCapture(fd)
        cap.start()
        os.write(fd, data)
        f = cap.done()
        s = f.read()
        assert s == "hello"
        f.close()

    def test_simple_many(self, tmpfile):
        for i in range(10):
            self.test_simple(tmpfile)

    def test_simple_many_check_open_files(self, testdir):
        with lsof_check():
            with testdir.makepyfile("").open('wb+') as tmpfile:
                self.test_simple_many(tmpfile)

    def test_simple_fail_second_start(self, tmpfile):
        fd = tmpfile.fileno()
        cap = capture.FDCapture(fd)
        f = cap.done()
        pytest.raises(ValueError, cap.start)
        f.close()

    def test_stderr(self):
        cap = capture.FDCapture(2, patchsys=True)
        cap.start()
        print_("hello", file=sys.stderr)
        f = cap.done()
        s = f.read()
        assert s == "hello\n"

    def test_stdin(self, tmpfile):
        tmpfile.write(tobytes("3"))
        tmpfile.seek(0)
        cap = capture.FDCapture(0, tmpfile=tmpfile)
        cap.start()
        # check with os.read() directly instead of raw_input(), because
        # sys.stdin itself may be redirected (as pytest now does by default)
        x = os.read(0, 100).strip()
        cap.done()
        assert x == tobytes("3")

    def test_writeorg(self, tmpfile):
        data1, data2 = tobytes("foo"), tobytes("bar")
        try:
            cap = capture.FDCapture(tmpfile.fileno())
            cap.start()
            tmpfile.write(data1)
            cap.writeorg(data2)
        finally:
            tmpfile.close()
        f = cap.done()
        scap = f.read()
        assert scap == totext(data1)
        stmp = open(tmpfile.name, 'rb').read()
        assert stmp == data2


class TestStdCapture:
    def getcapture(self, **kw):
        cap = capture.StdCapture(**kw)
        cap.startall()
        return cap

    def test_capturing_done_simple(self):
        cap = self.getcapture()
        sys.stdout.write("hello")
        sys.stderr.write("world")
        outfile, errfile = cap.done()
        s = outfile.read()
        assert s == "hello"
        s = errfile.read()
        assert s == "world"

    def test_capturing_reset_simple(self):
        cap = self.getcapture()
        print("hello world")
        sys.stderr.write("hello error\n")
        out, err = cap.reset()
        assert out == "hello world\n"
        assert err == "hello error\n"

    def test_capturing_readouterr(self):
        cap = self.getcapture()
        try:
            print ("hello world")
            sys.stderr.write("hello error\n")
            out, err = cap.readouterr()
            assert out == "hello world\n"
            assert err == "hello error\n"
            sys.stderr.write("error2")
        finally:
            out, err = cap.reset()
        assert err == "error2"

    def test_capturing_readouterr_unicode(self):
        cap = self.getcapture()
        try:
            print ("hx\xc4\x85\xc4\x87")
            out, err = cap.readouterr()
        finally:
            cap.reset()
        assert out == py.builtin._totext("hx\xc4\x85\xc4\x87\n", "utf8")

    @pytest.mark.skipif('sys.version_info >= (3,)',
                        reason='text output different for bytes on python3')
    def test_capturing_readouterr_decode_error_handling(self):
        cap = self.getcapture()
        # triggered a internal error in pytest
        print('\xa6')
        out, err = cap.readouterr()
        assert out == py.builtin._totext('\ufffd\n', 'unicode-escape')

    def test_reset_twice_error(self):
        cap = self.getcapture()
        print ("hello")
        out, err = cap.reset()
        pytest.raises(ValueError, cap.reset)
        assert out == "hello\n"
        assert not err

    def test_capturing_modify_sysouterr_in_between(self):
        oldout = sys.stdout
        olderr = sys.stderr
        cap = self.getcapture()
        sys.stdout.write("hello")
        sys.stderr.write("world")
        sys.stdout = capture.TextIO()
        sys.stderr = capture.TextIO()
        print ("not seen")
        sys.stderr.write("not seen\n")
        out, err = cap.reset()
        assert out == "hello"
        assert err == "world"
        assert sys.stdout == oldout
        assert sys.stderr == olderr

    def test_capturing_error_recursive(self):
        cap1 = self.getcapture()
        print ("cap1")
        cap2 = self.getcapture()
        print ("cap2")
        out2, err2 = cap2.reset()
        out1, err1 = cap1.reset()
        assert out1 == "cap1\n"
        assert out2 == "cap2\n"

    def test_just_out_capture(self):
        cap = self.getcapture(out=True, err=False)
        sys.stdout.write("hello")
        sys.stderr.write("world")
        out, err = cap.reset()
        assert out == "hello"
        assert not err

    def test_just_err_capture(self):
        cap = self.getcapture(out=False, err=True)
        sys.stdout.write("hello")
        sys.stderr.write("world")
        out, err = cap.reset()
        assert err == "world"
        assert not out

    def test_stdin_restored(self):
        old = sys.stdin
        cap = self.getcapture(in_=True)
        newstdin = sys.stdin
        out, err = cap.reset()
        assert newstdin != sys.stdin
        assert sys.stdin is old

    def test_stdin_nulled_by_default(self):
        print ("XXX this test may well hang instead of crashing")
        print ("XXX which indicates an error in the underlying capturing")
        print ("XXX mechanisms")
        cap = self.getcapture()
        pytest.raises(IOError, "sys.stdin.read()")
        out, err = cap.reset()

    def test_suspend_resume(self):
        cap = self.getcapture(out=True, err=False, in_=False)
        try:
            print ("hello")
            sys.stderr.write("error\n")
            out, err = cap.suspend()
            assert out == "hello\n"
            assert not err
            print ("in between")
            sys.stderr.write("in between\n")
            cap.resume()
            print ("after")
            sys.stderr.write("error_after\n")
        finally:
            out, err = cap.reset()
        assert out == "after\n"
        assert not err


class TestStdCaptureFD(TestStdCapture):
    pytestmark = needsosdup

    def getcapture(self, **kw):
        cap = capture.StdCaptureFD(**kw)
        cap.startall()
        return cap

    def test_intermingling(self):
        cap = self.getcapture()
        oswritebytes(1, "1")
        sys.stdout.write(str(2))
        sys.stdout.flush()
        oswritebytes(1, "3")
        oswritebytes(2, "a")
        sys.stderr.write("b")
        sys.stderr.flush()
        oswritebytes(2, "c")
        out, err = cap.reset()
        assert out == "123"
        assert err == "abc"

    def test_many(self, capfd):
        with lsof_check():
            for i in range(10):
                cap = capture.StdCaptureFD()
                cap.reset()


@needsosdup
def test_stdcapture_fd_tmpfile(tmpfile):
    capfd = capture.StdCaptureFD(out=tmpfile)
    try:
        os.write(1, "hello".encode("ascii"))
        os.write(2, "world".encode("ascii"))
        outf, errf = capfd.done()
    finally:
        capfd.reset()
    assert outf == tmpfile


class TestStdCaptureFDinvalidFD:
    pytestmark = needsosdup

    def test_stdcapture_fd_invalid_fd(self, testdir):
        testdir.makepyfile("""
            import os
            from _pytest.capture import StdCaptureFD
            def test_stdout():
                os.close(1)
                cap = StdCaptureFD(out=True, err=False, in_=False)
                cap.done()
            def test_stderr():
                os.close(2)
                cap = StdCaptureFD(out=False, err=True, in_=False)
                cap.done()
            def test_stdin():
                os.close(0)
                cap = StdCaptureFD(out=False, err=False, in_=True)
                cap.done()
        """)
        result = testdir.runpytest("--capture=fd")
        assert result.ret == 0
        assert result.parseoutcomes()['passed'] == 3


def test_capture_not_started_but_reset():
    capsys = capture.StdCapture()
    capsys.done()
    capsys.done()
    capsys.reset()


@needsosdup
def test_capture_no_sys():
    capsys = capture.StdCapture()
    try:
        cap = capture.StdCaptureFD(patchsys=False)
        cap.startall()
        sys.stdout.write("hello")
        sys.stderr.write("world")
        oswritebytes(1, "1")
        oswritebytes(2, "2")
        out, err = cap.reset()
        assert out == "1"
        assert err == "2"
    finally:
        capsys.reset()


@needsosdup
@pytest.mark.parametrize('use', [True, False])
def test_fdcapture_tmpfile_remains_the_same(tmpfile, use):
    if not use:
        tmpfile = True
    cap = capture.StdCaptureFD(out=False, err=tmpfile)
    try:
        cap.startall()
        capfile = cap.err.tmpfile
        cap.suspend()
        cap.resume()
    finally:
        cap.reset()
    capfile2 = cap.err.tmpfile
    assert capfile2 == capfile


@pytest.mark.parametrize('method', ['StdCapture', 'StdCaptureFD'])
def test_capturing_and_logging_fundamentals(testdir, method):
    if method == "StdCaptureFD" and not hasattr(os, 'dup'):
        pytest.skip("need os.dup")
    # here we check a fundamental feature
    p = testdir.makepyfile("""
        import sys, os
        import py, logging
        from _pytest import capture
        cap = capture.%s(out=False, in_=False)
        cap.startall()

        logging.warn("hello1")
        outerr = cap.suspend()
        print ("suspend, captured %%s" %%(outerr,))
        logging.warn("hello2")

        cap.resume()
        logging.warn("hello3")

        outerr = cap.suspend()
        print ("suspend2, captured %%s" %% (outerr,))
    """ % (method,))
    result = testdir.runpython(p)
    result.stdout.fnmatch_lines([
        "suspend, captured*hello1*",
        "suspend2, captured*hello2*WARNING:root:hello3*",
    ])
    assert "atexit" not in result.stderr.str()
