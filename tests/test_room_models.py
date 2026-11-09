import pytest
from services.room_service import validate_layout,available


def test_physical_model_exact_capacity():
    layout=validate_layout({'rows':4,'columns':3,'seats_per_bench':2,
            'seats':{'1/1/1':'blocked','1/2/1':'reserved','4/3/2':'accessible'}})
    assert available(layout)==22
    assert layout['rows']*layout['columns']==12


@pytest.mark.parametrize('states',[{'0/1/1':'blocked'},{'1/4/1':'reserved'},
 {'01/1/1':'blocked'},{'1/1/3':'accessible'},{'1/1/1':'unknown'},{'R1/1/1/1':'blocked'}])
def test_invalid_coordinates_and_states(states):
    with pytest.raises(ValueError):validate_layout({'rows':4,'columns':3,'seats_per_bench':2,'seats':states})


@pytest.mark.parametrize('rows,columns,seats',[(0,3,1),(51,3,1),(3,51,1),(3,3,7),(50,50,6)])
def test_room_resource_limits(rows,columns,seats):
    with pytest.raises(ValueError):validate_layout({'rows':rows,'columns':columns,'seats_per_bench':seats})
