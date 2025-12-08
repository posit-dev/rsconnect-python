import pytest

vetiver = pytest.importorskip("vetiver", reason="vetiver library not installed")

import os  # noqa
import pins  # noqa
import pandas as pd  # noqa
import numpy as np  # noqa

from pins.boards import BoardRsConnect  # noqa
from pins.rsconnect.api import RsConnectApi  # noqa
from pins.rsconnect.fs import RsConnectFs  # noqa
from rsconnect.api import RSConnectServer, RSConnectClient  # noqa

from .utils import require_api_key, require_connect  # noqa

pytestmark = pytest.mark.vetiver  # noqa

os.environ["CONNECT_CONTENT_BUILD_DIR"] = "vetiver-test-build"  # noqa


def rsc_delete_user_content(rsc):
    guid = rsc.get_user()["guid"]
    content = rsc.get_content(owner_guid=guid)
    for entry in content:
        rsc.delete_content_item(entry["guid"])


@pytest.fixture(scope="function")
def rsc_short():
    # tears down content after each test
    server_url = require_connect()
    api_key = require_api_key()
    rsc = RsConnectApi(server_url, api_key)
    fs_susan = RsConnectFs(rsc)

    # delete any content that might already exist
    rsc_delete_user_content(fs_susan.api)

    yield BoardRsConnect("", fs_susan, allow_pickle_read=True)  # fs_susan.ls to list content

    rsc_delete_user_content(fs_susan.api)


def test_deploy():
    server_url = require_connect()
    np.random.seed(500)

    # Load data, model
    X_df, y = vetiver.mock.get_mock_data()
    model = vetiver.mock.get_mock_model().fit(X_df, y)

    board = pins.board_rsconnect(server_url=server_url, api_key=require_api_key(), allow_pickle_read=True)
    username = board.fs.api.get_user()["username"]
    modelname = f"{username}/model"

    v = vetiver.VetiverModel(model=model, prototype_data=X_df, model_name=modelname)

    vetiver.vetiver_pin_write(board=board, model=v)
    connect_server = RSConnectServer(url=server_url, api_key=require_api_key())

    vetiver.deploy_connect(
        connect_server=connect_server,
        board=board,
        pin_name=modelname,
        title="testapivetiver",
        extra_files=["requirements.txt"],
    )

    # get url of where content lives
    client = RSConnectClient(connect_server)
    dicts = client.content_list()
    rsc_api = list(filter(lambda x: x["title"] == "testapivetiver", dicts))
    content_url = rsc_api[0].get("content_url")

    h = {"Authorization": "Key {}".format(require_api_key())}

    endpoint = vetiver.vetiver_endpoint(content_url + "/predict")
    response = vetiver.predict(endpoint, X_df, headers=h)

    assert isinstance(response, pd.DataFrame), response
    assert response.iloc[0, 0] == 44.47
    assert len(response) == 100
