import time

from func.subscriber import get_all_subscribers

from func.base import get_maestro_info, convert_maestro_attributes_to_dict

from func.account_feature import get_subscriber_feature_status, get_feature_info

from func.provisioning import create_provisioning

from func.cdr_record import get_latest_cdr_record_radius

from db import connect_to_db

from log import create_logger



import requests

import json





def align_essixpa_with_maestro(cursor, logger, subscribers, maestro, available_provider_ids, should_sleep, sleep_time):

    i = 0

    for i, subscriber in enumerate(subscribers):

        subscriber_name = subscriber['ext_sys_subscriber_id']

        base_maestro_attrs = {"name": subscriber_name}

        logger.info(f' - subscriber {i}')

        url = f'http://{maestro['ip_address']}:{str(maestro['port'])}/provision/v1/subscribers'

        result = requests.get(url, json=[base_maestro_attrs])

        res = result.json()

        success = res.get('totalSuccess')

        if success is not None and success == 1 and result.status_code == 200:

            # print(f" - subscriber exists on maestro")

            data = res['data'][0]

            # name = data['name']

            attributes = data['attributes']

            attributes_dict = convert_maestro_attributes_to_dict(attributes)

            # check that the blockSubscriber flag matches what we have in essixpa

            maestroBlockSubscriber = attributes_dict.get('blockSubscriber')

            if subscriber.usage_status == "BLOCKED" and (maestroBlockSubscriber is None or maestroBlockSubscriber == "false"):

                msg = f" - subscriber {subscriber_name} is not blocked on maestro but they should be. " \

                f"usage_status = {subscriber.usage_status} and maestroBlockSubscriber = {maestroBlockSubscriber}"

                logger.warning(msg)

                print(msg)

                create_provisioning(cursor,

                                    logger,

                                    ['provisioning_system_id', 'account_id', 'subscriber_id', 'tag'],

                                    [maestro.maestro_id, subscriber.account_id, subscriber.id, 'BLOCK-SUBSCRIBER']

                                    )

            elif subscriber.usage_status == "ACTIVE" and (maestroBlockSubscriber is None or maestroBlockSubscriber == "true"):

                msg = f" - subscriber {subscriber_name} is blocked on maestro but they should be ACTIVE" \

                      f"usage_status = {subscriber.usage_status} and maestroBlockSubscriber = {maestroBlockSubscriber}"

                logger.warning(msg)

                print(msg)

                create_provisioning(cursor,

                                    logger,

                                    ['provisioning_system_id', 'account_id', 'subscriber_id', 'tag'],

                                    [maestro.maestro_id, subscriber.account_id, subscriber.id, 'UNBLOCK-SUBSCRIBER']

                                    )

            else:

                msg = f" - subscriber {subscriber_name} has correct usage status: " \

                      f"essixpa -> [{subscriber.usage_status}], " \

                      f"maestro blockSubscriber -> [{attributes_dict['blockSubscriber']}]"

                logger.info(msg)

                print(msg)



            all_features = get_subscriber_feature_status(cursor, logger, subscriber.id)

            filters = json.loads(all_features.filters)

            shaping = json.loads(all_features.shaping)



            features = dict()

            features.update(filters)

            features.update(shaping) 

            for feature_name, value in features.items():

                maestro_filter = attributes_dict.get(feature_name)

                feature_info = None

                if maestro_filter is None:



                    msg = f" - feature {feature_name} for subscriber {subscriber_name} does not exist, need to create"

                    logger.warning(msg)

                    print(msg)

                    feature_info = get_feature_info(cursor, logger, feature_name)

                elif maestro_filter != value:

                    msg = f" - feature {feature_name} for subscriber {subscriber_name} has the wrong value. " \

                          f"should be {value} but its actually {maestro_filter}"

                    logger.warning(msg)

                    print(msg)

                    feature_info = get_feature_info(cursor, logger, feature_name)



                if feature_info:

                    if value == "true":

                        tag = "ENABLE-FEATURE"

                    else:

                        tag = "DISABLE-FEATURE"



                    create_provisioning(cursor,

                                        logger,

                                        ['provisioning_system_id', 'account_id', 'subscriber_id', 'feature_id', 'tag'],

                                        [maestro.maestro_id, subscriber.account_id, subscriber.id, feature_info.id, tag]

                                        )



            ProviderId = attributes_dict.get('ProviderId')

            Provider_Id = attributes_dict.get('Provider_Id')



            radius_row = get_latest_cdr_record_radius(cursor, subscriber_name)

            if not radius_row or radius_row is None:

                msg = f' - subscriber {subscriber_name} has not seen a radius message yet, nothing to do'

                logger.info(msg)

                print(msg)

                msg = ' ---'

                logger.info(msg)

                print(msg)

                if should_sleep:

                    time.sleep(sleep_time)

                continue



            logger.info(f' - subscriber {subscriber_name} current values are: '

                        f'ProviderId = [{ProviderId}], Provider_Id = [{Provider_Id}]')



            if radius_row.provider_id == '02':

                logger.info(' 02 is not a value provider_id so changing to O2')

                radius_row.provider_id = 'O2'  # need to be the letter O not a zero



            if radius_row.provider_id not in available_provider_ids and radius_row.provider_id != '02':

                msg = f' - subscriber {subscriber_name} has provider_id {radius_row.provider_id} that is not in' \

                      f' the accepted provider_ids {available_provider_ids}'

                logger.error(msg)

                print(msg)

                msg = ' ---'

                logger.info(msg)

                print(msg)

                if should_sleep:

                    time.sleep(sleep_time)

                continue



            if radius_row.provider_id != ProviderId or radius_row.provider_id != Provider_Id:

                logger.warning(f' - subscriber {subscriber_name} will have both provider_ids updated')

                url = f"http://{maestro['ip_address']}:{str(maestro['port'])}/provision/v1/subscribers"

                base_maestro_attrs['attributes'] = [{"name": "ProviderId", "value": radius_row.provider_id},

                                                    {"name": "Provider_Id", "value": radius_row.provider_id}

                                                   ]

                result = requests.patch(url, json=[base_maestro_attrs])

                res = result.json()

                success = res.get('totalSuccess')

                if success is None or success != 1 or result.status_code != 200:

                    msg = f' - failed to update subscriber {subscriber_name}: {res}'

                    logger.error(msg)

                    print(msg)

            else:

                msg = f' - subscriber {subscriber_name}\'s provider_ids match {radius_row.provider_id}'

                logger.info(msg)

                print(msg)



            msg = f' ---'

            logger.info(msg)

            print(msg)



            if should_sleep:

                time.sleep(sleep_time)



        else:

            msg = f" - subscriber {subscriber_name} does not exist maestro, need to create them"

            logger.warning(msg)

            print(msg)

            create_provisioning(cursor,

                                logger,

                                ['provisioning_system_id', 'account_id', 'subscriber_id', 'tag'],

                                [maestro.maestro_id, subscriber.account_id, subscriber.id, 'CREATE-SUBSCRIBER']

                                )

            msg = ' ---'

            logger.info(msg)

            print(msg)

            if should_sleep:

                time.sleep(sleep_time)



    msg = f"checked {i} subscribers"

    logger.info(msg)

    print(msg)





if __name__ == "__main__":



    conn = connect_to_db(autocommit=True)

    cursor = conn.cursor()

    subscribers = get_all_subscribers(cursor)

    logger = create_logger('essixpa-scripts-maestro-sync.log')

    maestro = get_maestro_info(cursor)



    available_provider_ids = ['EE', 'O2', 'TF', 'KPN']



    should_sleep = False

    sleep_time = 3

    try:

        align_essixpa_with_maestro(cursor, logger, subscribers, maestro, available_provider_ids, should_sleep, sleep_time)

    except Exception as e:

        logger.error(f" - error when running align_essixpa_with_maestro: {e}")

        exit(f" - error when running align_essixpa_with_maestro: {e}")



    exit("exiting")