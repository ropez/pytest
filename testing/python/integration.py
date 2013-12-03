import pytest
from _pytest import runner
from _pytest import python

class TestOEJSKITSpecials:
    def test_funcarg_non_pycollectobj(self, testdir): # rough jstests usage
        testdir.makeconftest("""
            import pytest
            def pytest_pycollect_makeitem(collector, name, obj):
                if name == "MyClass":
                    return MyCollector(name, parent=collector)
            class MyCollector(pytest.Collector):
                def reportinfo(self):
                    return self.fspath, 3, "xyz"
        """)
        modcol = testdir.getmodulecol("""
            def pytest_funcarg__arg1(request):
                return 42
            class MyClass:
                pass
        """)
        # this hook finds funcarg factories
        rep = runner.collect_one_node(collector=modcol)
        clscol = rep.result[0]
        clscol.obj = lambda arg1: None
        clscol.funcargs = {}
        pytest._fillfuncargs(clscol)
        assert clscol.funcargs['arg1'] == 42

    def test_autouse_fixture(self, testdir): # rough jstests usage
        testdir.makeconftest("""
            import pytest
            def pytest_pycollect_makeitem(collector, name, obj):
                if name == "MyClass":
                    return MyCollector(name, parent=collector)
            class MyCollector(pytest.Collector):
                def reportinfo(self):
                    return self.fspath, 3, "xyz"
        """)
        modcol = testdir.getmodulecol("""
            import pytest
            @pytest.fixture(autouse=True)
            def hello():
                pass
            def pytest_funcarg__arg1(request):
                return 42
            class MyClass:
                pass
        """)
        # this hook finds funcarg factories
        rep = runner.collect_one_node(modcol)
        clscol = rep.result[0]
        clscol.obj = lambda: None
        clscol.funcargs = {}
        pytest._fillfuncargs(clscol)
        assert not clscol.funcargs


def test_wrapped_getfslineno():
    def func():
        pass
    def wrap(f):
        func.__wrapped__ = f
        func.patchings = ["qwe"]
        return func
    @wrap
    def wrapped_func(x, y, z):
        pass
    fs, lineno = python.getfslineno(wrapped_func)
    fs2, lineno2 = python.getfslineno(wrap)
    assert lineno > lineno2, "getfslineno does not unwrap correctly"

class TestMockDecoration:
    def test_wrapped_getfuncargnames(self):
        from _pytest.python import getfuncargnames
        def wrap(f):
            def func():
                pass
            func.__wrapped__ = f
            return func
        @wrap
        def f(x):
            pass
        l = getfuncargnames(f)
        assert l == ("x",)

    def test_wrapped_getfuncargnames_patching(self):
        from _pytest.python import getfuncargnames
        def wrap(f):
            def func():
                pass
            func.__wrapped__ = f
            func.patchings = ["qwe"]
            return func
        @wrap
        def f(x, y, z):
            pass
        l = getfuncargnames(f)
        assert l == ("y", "z")

    def test_unittest_mock(self, testdir):
        pytest.importorskip("unittest.mock")
        testdir.makepyfile("""
            import unittest.mock
            class T(unittest.TestCase):
                @unittest.mock.patch("os.path.abspath")
                def test_hello(self, abspath):
                    import os
                    os.path.abspath("hello")
                    abspath.assert_any_call("hello")
        """)
        reprec = testdir.inline_run()
        reprec.assertoutcome(passed=1)

    def test_mock(self, testdir):
        pytest.importorskip("mock", "1.0.1")
        testdir.makepyfile("""
            import os
            import unittest
            import mock

            class T(unittest.TestCase):
                @mock.patch("os.path.abspath")
                def test_hello(self, abspath):
                    os.path.abspath("hello")
                    abspath.assert_any_call("hello")
            @mock.patch("os.path.abspath")
            @mock.patch("os.path.normpath")
            def test_someting(normpath, abspath, tmpdir):
                abspath.return_value = "this"
                os.path.normpath(os.path.abspath("hello"))
                normpath.assert_any_call("this")
        """)
        reprec = testdir.inline_run()
        reprec.assertoutcome(passed=2)
        calls = reprec.getcalls("pytest_runtest_logreport")
        funcnames = [call.report.location[2] for call in calls
                        if call.report.when == "call"]
        assert funcnames == ["T.test_hello", "test_someting"]

    def test_mock_sorting(self, testdir):
        pytest.importorskip("mock", "1.0.1")
        testdir.makepyfile("""
            import os
            import mock

            @mock.patch("os.path.abspath")
            def test_one(abspath):
                pass
            @mock.patch("os.path.abspath")
            def test_two(abspath):
                pass
            @mock.patch("os.path.abspath")
            def test_three(abspath):
                pass
        """)
        reprec = testdir.inline_run()
        calls = reprec.getreports("pytest_runtest_logreport")
        calls = [x for x in calls if x.when == "call"]
        names = [x.nodeid.split("::")[-1] for x in calls]
        assert names == ["test_one", "test_two", "test_three"]


class TestReRunTests:
    def test_rerun(self, testdir):
        testdir.makeconftest("""
            from _pytest.runner import runtestprotocol
            def pytest_runtest_protocol(item, nextitem):
                runtestprotocol(item, log=False, nextitem=nextitem)
                runtestprotocol(item, log=True, nextitem=nextitem)
        """)
        testdir.makepyfile("""
            import pytest
            count = 0
            req = None
            @pytest.fixture
            def fix(request):
                global count, req
                assert request != req
                req = request
                print ("fix count %s" % count)
                count += 1
            def test_fix(fix):
                pass
        """)
        result = testdir.runpytest("-s")
        result.stdout.fnmatch_lines("""
            *fix count 0*
            *fix count 1*
        """)
        result.stdout.fnmatch_lines("""
            *2 passed*
        """)

def test_pytestconfig_is_session_scoped():
    from _pytest.python import pytestconfig
    assert pytestconfig._pytestfixturefunction.scope == "session"
