from person_role_checks import role_tenures


def test_explicit_two_appointments_share_a_term_despite_semicolon_and_nominating_chairman():
    text='2018年会议选举林知远为董事长；同日经董事长提名、提名委员会审核聘任其为总裁，任期均三年至董事会届满。'
    assert set(role_tenures(text))=={('董事长','3年'),('总裁','3年')}


def test_shared_prefix_term_also_applies_to_both_explicit_appointments():
    text='会议选举林知远为董事长，同日经董事长提名、委员会审核聘任总裁，均任期三年。'
    assert set(role_tenures(text))=={('董事长','3年'),('总裁','3年')}


def test_nominating_chairman_without_appointment_never_gets_the_president_term():
    for text in ['经董事长提名、委员会审核，聘任其为总裁，任期三年。',
                 '经董事长提名，聘任两名总裁，任期均三年。',
                 '另次会议选举林知远为董事长。经董事长提名，聘任总裁，任期均三年。']:
        assert role_tenures(text)==[('总裁','3年')]
