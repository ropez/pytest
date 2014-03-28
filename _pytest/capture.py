"""
per-test stdout/stderr capturing mechanism.

"""
from __future__ import with_statement

import sys
import os
from tempfile import TemporaryFile
import contextlib

import py
import pytest

try:
    from io import StringIO
except ImportError:
    from StringIO import StringIO

try:
    from io import BytesIO
except ImportError:
    class BytesIO(StringIO):
        def write(self, data):
            if isinstance(data, unicode):
                raise TypeError("not a byte value: %r" % (data,))
            StringIO.write(self, data)

if sys.version_info < (3, 0):
    class TextIO(StringIO):
        def write(self, data):
            if not isinstance(data, unicode):
                enc = getattr(self, '_encoding', 'UTF-8')
                data = unicode(data, enc, 'replace')
            StringIO.write(self, data)
else:
    TextIO = StringIO


patchsysdict = {0: 'stdin', 1: 'stdout', 2: 'stderr'}


def pytest_addoption(parser):
    group = parser.getgroup("general")
    group._addoption(
        '--capture', action="store", default=None,
        metavar="method", choices=['fd', 'sys', 'no'],
        help="per-test capturing method: one of fd (default)|sys|no.")
    group._addoption(
        '-s', action="store_const", const="no", dest="capture",
        help="shortcut for --capture=no.")


@pytest.mark.tryfirst
def pytest_load_initial_conftests(early_config, parser, args, __multicall__):
    ns = parser.parse_known_args(args)
    method = ns.capture
    if not method:
        method = "fd"
    if method == "fd" and not hasattr(os, "dup"):
        method = "sys"
    pluginmanager = early_config.pluginmanager
    if method != "no":
        try:
            sys.stdout.fileno()
        except Exception:
            dupped_stdout = sys.stdout
        else:
            dupped_stdout = dupfile(sys.stdout, buffering=1)
        pluginmanager.register(dupped_stdout, "dupped_stdout")
            #pluginmanager.add_shutdown(dupped_stdout.close)
    capman = CaptureManager(method)
    pluginmanager.register(capman, "capturemanager")

    # make sure that capturemanager is properly reset at final shutdown
    def teardown():
        try:
            capman.reset_capturings()
        except ValueError:
            pass

    pluginmanager.add_shutdown(teardown)

    # make sure logging does not raise exceptions at the end
    def silence_logging_at_shutdown():
        if "logging" in sys.modules:
            sys.modules["logging"].raiseExceptions = False
    pluginmanager.add_shutdown(silence_logging_at_shutdown)

    # finally trigger conftest loading but while capturing (issue93)
    capman.resumecapture()
    try:
        try:
            return __multicall__.execute()
        finally:
            out, err = capman.suspendcapture()
    except:
        sys.stdout.write(out)
        sys.stderr.write(err)
        raise



class CaptureManager:
    def __init__(self, defaultmethod=None):
        self._method2capture = {}
        self._defaultmethod = defaultmethod

    def _getcapture(self, method):
        if method == "fd":
            return StdCaptureBase(out=True, err=True, Capture=FDCapture)
        elif method == "sys":
            return StdCaptureBase(out=True, err=True, Capture=SysCapture)
        elif method == "no":
            return StdCaptureBase(out=False, err=False, in_=False)
        else:
            raise ValueError("unknown capturing method: %r" % method)

    def _getmethod(self, config, fspath):
        if config.option.capture:
            method = config.option.capture
        else:
            try:
                method = config._conftest.rget("option_capture", path=fspath)
            except KeyError:
                method = "fd"
        if method == "fd" and not hasattr(os, 'dup'):  # e.g. jython
            method = "sys"
        return method

    def reset_capturings(self):
        for cap in self._method2capture.values():
            cap.pop_outerr_to_orig()
            cap.stop_capturing()
        self._method2capture.clear()

    def resumecapture_item(self, item):
        method = self._getmethod(item.config, item.fspath)
        return self.resumecapture(method)

    def resumecapture(self, method=None):
        if hasattr(self, '_capturing'):
            raise ValueError(
                "cannot resume, already capturing with %r" %
                (self._capturing,))
        if method is None:
            method = self._defaultmethod
        cap = self._method2capture.get(method)
        self._capturing = method
        if cap is None:
            self._method2capture[method] = cap = self._getcapture(method)
            cap.start_capturing()
        else:
            cap.pop_outerr_to_orig()

    def suspendcapture(self, item=None):
        self.deactivate_funcargs()
        method = self.__dict__.pop("_capturing", None)
        if method is not None:
            cap = self._method2capture.get(method)
            if cap is not None:
                return cap.readouterr()
        return "", ""

    def activate_funcargs(self, pyfuncitem):
        capfuncarg = pyfuncitem.__dict__.pop("_capfuncarg", None)
        if capfuncarg is not None:
            capfuncarg._start()
            self._capfuncarg = capfuncarg

    def deactivate_funcargs(self):
        capfuncarg = self.__dict__.pop("_capfuncarg", None)
        if capfuncarg is not None:
            capfuncarg.close()

    @pytest.mark.hookwrapper
    def pytest_make_collect_report(self, __multicall__, collector):
        method = self._getmethod(collector.config, collector.fspath)
        try:
            self.resumecapture(method)
        except ValueError:
            yield
            # recursive collect, XXX refactor capturing
            # to allow for more lightweight recursive capturing
            return
        yield
        out, err = self.suspendcapture()
        # XXX getting the report from the ongoing hook call is a bit
        # of a hack.  We need to think about capturing during collection
        # and find out if it's really needed fine-grained (per
        # collector).
        if __multicall__.results:
            rep = __multicall__.results[0]
            if out:
                rep.sections.append(("Captured stdout", out))
            if err:
                rep.sections.append(("Captured stderr", err))

    @pytest.mark.hookwrapper
    def pytest_runtest_setup(self, item):
        with self.item_capture_wrapper(item, "setup"):
            yield

    @pytest.mark.hookwrapper
    def pytest_runtest_call(self, item):
        with self.item_capture_wrapper(item, "call"):
            self.activate_funcargs(item)
            yield
            #self.deactivate_funcargs() called from ctx's suspendcapture()

    @pytest.mark.hookwrapper
    def pytest_runtest_teardown(self, item):
        with self.item_capture_wrapper(item, "teardown"):
            yield

    @pytest.mark.tryfirst
    def pytest_keyboard_interrupt(self, excinfo):
        self.reset_capturings()

    @pytest.mark.tryfirst
    def pytest_internalerror(self, excinfo):
        self.reset_capturings()

    @contextlib.contextmanager
    def item_capture_wrapper(self, item, when):
        self.resumecapture_item(item)
        yield
        out, err = self.suspendcapture(item)
        item.add_report_section(when, "out", out)
        item.add_report_section(when, "err", err)

error_capsysfderror = "cannot use capsys and capfd at the same time"


def pytest_funcarg__capsys(request):
    """enables capturing of writes to sys.stdout/sys.stderr and makes
    captured output available via ``capsys.readouterr()`` method calls
    which return a ``(out, err)`` tuple.
    """
    if "capfd" in request._funcargs:
        raise request.raiseerror(error_capsysfderror)
    request.node._capfuncarg = c = CaptureFixture(SysCapture)
    return c

def pytest_funcarg__capfd(request):
    """enables capturing of writes to file descriptors 1 and 2 and makes
    captured output available via ``capsys.readouterr()`` method calls
    which return a ``(out, err)`` tuple.
    """
    if "capsys" in request._funcargs:
        request.raiseerror(error_capsysfderror)
    if not hasattr(os, 'dup'):
        pytest.skip("capfd funcarg needs os.dup")
    request.node._capfuncarg = c = CaptureFixture(FDCapture)
    return c


class CaptureFixture:
    def __init__(self, captureclass):
        self.captureclass = captureclass

    def _start(self):
        self._capture = StdCaptureBase(out=True, err=True, in_=False,
                                       Capture=self.captureclass)
        self._capture.start_capturing()

    def close(self):
        cap = self.__dict__.pop("_capture", None)
        if cap is not None:
            cap.pop_outerr_to_orig()
            cap.stop_capturing()

    def readouterr(self):
        try:
            return self._capture.readouterr()
        except AttributeError:
            return "", ""


def dupfile(f, mode=None, buffering=0, raising=False, encoding=None):
    """ return a new open file object that's a duplicate of f

        mode is duplicated if not given, 'buffering' controls
        buffer size (defaulting to no buffering) and 'raising'
        defines whether an exception is raised when an incompatible
        file object is passed in (if raising is False, the file
        object itself will be returned)
    """
    try:
        fd = f.fileno()
        mode = mode or f.mode
    except AttributeError:
        if raising:
            raise
        return f
    newfd = os.dup(fd)
    if sys.version_info >= (3, 0):
        if encoding is not None:
            mode = mode.replace("b", "")
            buffering = True
        return os.fdopen(newfd, mode, buffering, encoding, closefd=True)
    else:
        f = os.fdopen(newfd, mode, buffering)
        if encoding is not None:
            return EncodedFile(f, encoding)
        return f


class EncodedFile(object):
    def __init__(self, _stream, encoding):
        self._stream = _stream
        self.encoding = encoding

    def write(self, obj):
        if isinstance(obj, unicode):
            obj = obj.encode(self.encoding)
        self._stream.write(obj)

    def writelines(self, linelist):
        data = ''.join(linelist)
        self.write(data)

    def __getattr__(self, name):
        return getattr(self._stream, name)


class StdCaptureBase(object):
    out = err = in_ = None

    def __init__(self, out=True, err=True, in_=True, Capture=None):
        if in_:
            self.in_ = Capture(0)
        if out:
            self.out = Capture(1)
        if err:
            self.err = Capture(2)

    def start_capturing(self):
        if self.in_:
            self.in_.start()
        if self.out:
            self.out.start()
        if self.err:
            self.err.start()

    def pop_outerr_to_orig(self):
        """ pop current snapshot out/err capture and flush to orig streams. """
        out, err = self.readouterr()
        if out:
            self.out.writeorg(out)
        if err:
            self.err.writeorg(err)

    def stop_capturing(self):
        """ stop capturing and reset capturing streams """
        if hasattr(self, '_reset'):
            raise ValueError("was already stopped")
        self._reset = True
        if self.out:
            self.out.done()
        if self.err:
            self.err.done()
        if self.in_:
            self.in_.done()

    def readouterr(self):
        """ return snapshot unicode value of stdout/stderr capturings. """
        return self._readsnapshot('out'), self._readsnapshot('err')

    def _readsnapshot(self, name):
        cap = getattr(self, name, None)
        if cap is None:
            return ""
        return cap.snap()


class FDCapture:
    """ Capture IO to/from a given os-level filedescriptor. """

    def __init__(self, targetfd, tmpfile=None):
        self.targetfd = targetfd
        try:
            self._savefd = os.dup(self.targetfd)
        except OSError:
            self.start = lambda: None
            self.done = lambda: None
        else:
            if tmpfile is None:
                if targetfd == 0:
                    tmpfile = open(os.devnull, "r")
                else:
                    f = TemporaryFile()
                    with f:
                        tmpfile = dupfile(f, encoding="UTF-8")
            self.tmpfile = tmpfile
            if targetfd in patchsysdict:
                self._oldsys = getattr(sys, patchsysdict[targetfd])

    def __repr__(self):
        return "<FDCapture %s oldfd=%s>" % (self.targetfd, self._savefd)

    def start(self):
        """ Start capturing on targetfd using memorized tmpfile. """
        try:
            os.fstat(self._savefd)
        except OSError:
            raise ValueError("saved filedescriptor not valid anymore")
        targetfd = self.targetfd
        os.dup2(self.tmpfile.fileno(), targetfd)
        if hasattr(self, '_oldsys'):
            subst = self.tmpfile if targetfd != 0 else DontReadFromInput()
            setattr(sys, patchsysdict[targetfd], subst)

    def snap(self):
        f = self.tmpfile
        f.seek(0)
        res = f.read()
        if res:
            enc = getattr(f, "encoding", None)
            if enc and isinstance(res, bytes):
                res = py.builtin._totext(res, enc, "replace")
            f.truncate(0)
            f.seek(0)
        return res

    def done(self):
        """ stop capturing, restore streams, return original capture file,
        seeked to position zero. """
        os.dup2(self._savefd, self.targetfd)
        os.close(self._savefd)
        if hasattr(self, '_oldsys'):
            setattr(sys, patchsysdict[self.targetfd], self._oldsys)
        self.tmpfile.close()

    def writeorg(self, data):
        """ write to original file descriptor. """
        if py.builtin._istext(data):
            data = data.encode("utf8") # XXX use encoding of original stream
        os.write(self._savefd, data)


class SysCapture:
    def __init__(self, fd):
        name = patchsysdict[fd]
        self._old = getattr(sys, name)
        self.name = name
        if name == "stdin":
            self.tmpfile = DontReadFromInput()
        else:
            self.tmpfile = TextIO()

    def start(self):
        setattr(sys, self.name, self.tmpfile)

    def snap(self):
        f = self.tmpfile
        res = f.getvalue()
        f.truncate(0)
        f.seek(0)
        return res

    def done(self):
        setattr(sys, self.name, self._old)
        self.tmpfile.close()

    def writeorg(self, data):
        self._old.write(data)
        self._old.flush()


class DontReadFromInput:
    """Temporary stub class.  Ideally when stdin is accessed, the
    capturing should be turned off, with possibly all data captured
    so far sent to the screen.  This should be configurable, though,
    because in automated test runs it is better to crash than
    hang indefinitely.
    """
    def read(self, *args):
        raise IOError("reading from stdin while output is captured")
    readline = read
    readlines = read
    __iter__ = read

    def fileno(self):
        raise ValueError("redirected Stdin is pseudofile, has no fileno()")

    def isatty(self):
        return False

    def close(self):
        pass
