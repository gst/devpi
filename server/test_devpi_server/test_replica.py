import pytest
import py
from devpi_server.replica import *
from devpi_common.url import URL

def loads(bytestring):
    return load(py.io.BytesIO(bytestring))

pytestmark = [pytest.mark.notransaction]

def test_view_name2serials(pypistage, testapp):
    pypistage.mock_simple("package", '<a href="/package-1.0.zip" />',
                          pypiserial=15)
    r = testapp.get("/root/pypi/+name2serials", expect_errors=False)
    io = py.io.BytesIO(r.body)
    entries = load(io)
    assert entries["package"] == 15


class TestChangelog:
    def get_latest_serial(self, testapp):
        r = testapp.get("/+changelog/nop", expect_errors=False)
        return int(r.headers["X-DEVPI-SERIAL"])

    def test_get_latest_serial(self, testapp, mapp):
        latest_serial = self.get_latest_serial(testapp)
        assert latest_serial >= -1
        mapp.create_user("hello", "pass")
        assert self.get_latest_serial(testapp) == latest_serial + 1

    def test_get_since(self, testapp, mapp, noiter):
        mapp.create_user("this", password="p")
        latest_serial = self.get_latest_serial(testapp)
        r = testapp.get("/+changelog/%s" % latest_serial, expect_errors=False)
        body = b''.join(r.app_iter)
        data = loads(body)
        assert "this" in str(data)

    def test_get_wait(self, testapp, mapp, noiter, monkeypatch):
        mapp.create_user("this", password="p")
        latest_serial = self.get_latest_serial(testapp)
        monkeypatch.setattr(testapp.xom.keyfs.notifier.cv_new_transaction,
                            "wait", lambda *x: 0/0)
        with pytest.raises(ZeroDivisionError):
            testapp.get("/+changelog/%s" % (latest_serial+1,),
                        expect_errors=False)


class TestPyPIProxy:
    def test_pypi_proxy(self, xom, reqmock):
        from devpi_server.keyfs import dump
        url = "http://localhost:3141/root/pypi/+name2serials"
        master_url = URL("http://localhost:3141")
        proxy = PyPIProxy(xom._httpsession, master_url)
        io = py.io.BytesIO()
        dump({"hello": 42}, io)
        data = io.getvalue()
        reqmock.mockresponse(url=url, code=200, method="GET", data=data)
        name2serials = proxy.list_packages_with_serial()
        assert name2serials == {"hello": 42}

    def test_replica_startup(self, replica_xom):
        assert isinstance(replica_xom.proxy, PyPIProxy)


def test_pypi_project_changed(replica_xom):
    handler = PypiProjectChanged(replica_xom)
    class Ev:
        value = dict(projectname="newproject", serial=12)
        typedkey = replica_xom.keyfs.get_key("PYPILINKS")
    handler(Ev())
    assert replica_xom.pypimirror.name2serials["newproject"] == 12
    class Ev2:
        value = dict(projectname="newproject", serial=15)
        typedkey = replica_xom.keyfs.get_key("PYPILINKS")
    handler(Ev2())
    assert replica_xom.pypimirror.name2serials["newproject"] == 15

class TestReplicaThread:
    @pytest.fixture
    def rt(self, makexom):
        xom = makexom(["--master=http://localhost"])
        rt = ReplicaThread(xom)
        xom.thread_pool.register(rt)
        return rt

    def test_thread_run_fail(self, rt, reqmock, caplog):
        rt.thread.sleep = lambda x: 0/0
        reqmock.mockresponse("http://localhost/+changelog/1", code=404)
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("404.*failed fetching*")

    def test_thread_run_decode_error(self, rt, reqmock, caplog):
        rt.thread.sleep = lambda x: 0/0
        reqmock.mockresponse("http://localhost/+changelog/1", code=200,
                             data=b'qlwekj')
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("could not read answer")

    def test_thread_run_ok(self, rt, reqmock, caplog):
        rt.thread.sleep = rt.thread.exit_if_shutdown = lambda *x: 0/0
        reqmock.mockresponse("http://localhost/+changelog/1", code=200,
                             data=rt.xom.keyfs._fs.get_raw_changelog_entry(0))
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("committed")
