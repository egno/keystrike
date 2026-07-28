from keystrike.infrastructure.id_gen import UlidGenerator


def test_ulid_length_and_alphabet():
    gen = UlidGenerator()
    for _ in range(10):
        ulid = gen.new_id()
        assert len(ulid) == 26
        assert all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in ulid)


def test_ulids_are_unique():
    gen = UlidGenerator()
    ids = {gen.new_id() for _ in range(1000)}
    assert len(ids) == 1000
