# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import os
import subprocess
import time

from isaac_ros_test import IsaacROSBaseTest, JSONConversion

from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

import pytest
import rclpy

from sensor_msgs.msg import CameraInfo, Image
from stereo_msgs.msg import DisparityImage


@pytest.mark.rostest
def generate_test_description():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    engine_file_path = '/tmp/dummy_model.engine'
    if not os.path.isfile(engine_file_path):
        args = [
            '/usr/src/tensorrt/bin/trtexec',
            f'--saveEngine={engine_file_path}',
            f'--onnx={dir_path}/dummy_model.onnx'
        ]
        print('Generating model engine file by command: ', ' '.join(args))
        result = subprocess.run(
            args,
            env=os.environ,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if result.returncode != 0:
            raise Exception(
                f'Failed to convert with status: {result.returncode}.\n'
                f'stderr:\n' + result.stderr.decode('utf-8')
            )

    disparity_node = ComposableNode(
        name='disparity',
        package='isaac_ros_ess',
        plugin='nvidia::isaac_ros::dnn_stereo_disparity::ESSDisparityNode',
        namespace=IsaacROSDisparityTest.generate_namespace(),
        parameters=[{'engine_file_path': engine_file_path}],
    )

    container = ComposableNodeContainer(
        name='disparity_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container',
        composable_node_descriptions=[disparity_node],
        output='screen',
        arguments=['--ros-args', '--log-level', 'info']
    )
    return IsaacROSDisparityTest.generate_test_description([container])


class IsaacROSDisparityTest(IsaacROSBaseTest):
    IMAGE_HEIGHT = 1080
    IMAGE_WIDTH = 1920
    TIMEOUT = 10
    ENGINE_FILE_PATH = '/tmp/dummy_model.engine'
    CAMERA_INFO_PATH = os.path.dirname(os.path.realpath(__file__)) + '/camera_info.json'

    def _create_image(self):
        image = Image()
        image.height = self.IMAGE_HEIGHT
        image.width = self.IMAGE_WIDTH
        image.encoding = 'rgb8'
        image.is_bigendian = False
        image.step = self.IMAGE_WIDTH * 3
        image.data = [0] * self.IMAGE_HEIGHT * self.IMAGE_WIDTH * 3
        return image

    def test_image_disparity(self):
        end_time = time.time() + self.TIMEOUT
        while time.time() < end_time:
            if os.path.isfile(self.ENGINE_FILE_PATH):
                break
        self.assertTrue(os.path.isfile(self.ENGINE_FILE_PATH),
                        'Model engine file was not generated in time.')

        received_messages = {}
        self.generate_namespace_lookup(['left/image_rect', 'right/image_rect',
                                        'left/camera_info', 'right/camera_info',
                                        'disparity'])

        subs = self.create_logging_subscribers(
            [('disparity', DisparityImage)], received_messages)

        image_left_pub = self.node.create_publisher(
            Image, self.namespaces['left/image_rect'], self.DEFAULT_QOS
        )
        image_right_pub = self.node.create_publisher(
            Image, self.namespaces['right/image_rect'], self.DEFAULT_QOS
        )
        camera_info_left = self.node.create_publisher(
            CameraInfo, self.namespaces['left/camera_info'], self.DEFAULT_QOS
        )
        camera_info_right = self.node.create_publisher(
            CameraInfo, self.namespaces['right/camera_info'], self.DEFAULT_QOS
        )

        try:
            left_image = self._create_image()
            right_image = self._create_image()
            camera_info = JSONConversion.load_camera_info_from_json(self.CAMERA_INFO_PATH)

            end_time = time.time() + self.TIMEOUT
            done = False

            while time.time() < end_time:
                image_left_pub.publish(left_image)
                image_right_pub.publish(right_image)
                camera_info_left.publish(camera_info)
                camera_info_right.publish(camera_info)

                rclpy.spin_once(self.node, timeout_sec=0.1)

                if 'disparity' in received_messages:
                    done = True
                    break
            self.assertTrue(done, 'Didnt recieve output on disparity topic')

            disparity = received_messages['disparity']
            self.assertEqual(disparity.image.encoding, '32FC1')
            self.assertEqual(disparity.image.height, self.IMAGE_HEIGHT)
            self.assertEqual(disparity.image.width, self.IMAGE_WIDTH)
            self.assertEqual(disparity.image.step, self.IMAGE_WIDTH * 4)
            self.assertAlmostEqual(disparity.f, -0.3678634)
            self.assertAlmostEqual(disparity.t, 434.9440002)
            self.assertAlmostEqual(disparity.min_disparity, 0.0)
            self.assertAlmostEqual(disparity.max_disparity, 2147483648.0)

        finally:
            [self.node.destroy_subscription(sub) for sub in subs]
            self.node.destroy_publisher(image_left_pub)
            self.node.destroy_publisher(image_right_pub)
            self.node.destroy_publisher(camera_info_right)
            self.node.destroy_publisher(camera_info_left)
