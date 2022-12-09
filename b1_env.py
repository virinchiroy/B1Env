from pdb import set_trace
from typing import Optional

import numpy as np
import pinocchio as pin
import pybullet as p
import pybullet_data
from gymnasium import Env, spaces
from pinocchio.robot_wrapper import RobotWrapper


class B1Sim(Env):
    def __init__(
        self, render_mode: Optional[str] = None, record_path=None, useFixedBase=False
    ):
        if render_mode == "human":
            self.client = p.connect(p.GUI)
            # Improves rendering performance on M1 Macs
            p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
        else:
            self.client = p.connect(p.DIRECT)

        p.setGravity(0, 0, -9.81)
        p.setTimeStep(1 / 240)

        # Load plane
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.loadURDF("plane.urdf")

        # Load Franka Research 3 Robot
        package_directory = "/Users/bolundai/Documents/B1Env"
        robot_URDF = package_directory + "/robots/b1_box_collide.urdf"
        urdf_search_path = package_directory + "/robots"
        p.setAdditionalSearchPath(urdf_search_path)
        self.robotID = p.loadURDF(
            "b1_box_collide.urdf", [0.0, 0.0, 1.0], useFixedBase=useFixedBase
        )

        # Build pin_robot
        self.robot = RobotWrapper.BuildFromURDF(robot_URDF, package_directory)

        # Get number of joints
        self.n_j = p.getNumJoints(self.robotID)

        # Set observation and action space
        obs_low_q = []
        obs_low_dq = []
        obs_high_q = []
        obs_high_dq = []
        _act_low = []
        _act_high = []
        self.active_joint_ids = []

        for i in range(self.n_j):
            _joint_infos = p.getJointInfo(self.robotID, i)

            if _joint_infos[2] != p.JOINT_FIXED:
                obs_low_q.append(_joint_infos[8])
                obs_high_q.append(_joint_infos[9])
                obs_low_dq.append(-_joint_infos[11])
                obs_high_dq.append(_joint_infos[11])
                _act_low.append(-_joint_infos[10])
                _act_high.append(_joint_infos[10])
                self.active_joint_ids.append(i)

        # Disable the velocity control on the joints as we use torque control.
        p.setJointMotorControlArray(
            self.robotID,
            self.active_joint_ids,
            p.VELOCITY_CONTROL,
            forces=np.zeros(len(self.active_joint_ids)),
        )

        obs_low = np.array(obs_low_q + obs_low_dq, dtype=np.float32)
        obs_high = np.array(obs_high_q + obs_high_dq, dtype=np.float32)
        act_low = np.array(_act_low, dtype=np.float32)
        act_high = np.array(_act_high, dtype=np.float32)

        self.observation_space = spaces.Box(obs_low, obs_high, dtype=np.float32)
        self.action_space = spaces.Box(act_low, act_high, dtype=np.float32)

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ):
        target_joint_angles = 12 * [0.0]

        for i, joint_ang in enumerate(target_joint_angles):
            p.resetJointState(self.robotID, self.active_joint_ids[i], joint_ang, 0.0)

        q, dq = self.get_state_update_pinocchio()
        info = self.get_info(q, dq)

        return info

    def step(self, action):
        self.send_joint_command(action)
        p.stepSimulation()

        q, dq = self.get_state_update_pinocchio()
        info = self.get_info(q, dq)

        return info

    def get_info(self, q, dq):
        info = {
            "q": q,
            "dq": dq,
        }

        return info

    def close(self):
        p.disconnect()

    def get_state(self):
        q = np.zeros(12)
        dq = np.zeros(12)

        for i, id in enumerate(self.active_joint_ids):
            _joint_state = p.getJointState(self.robotID, id)
            q[i], dq[i] = _joint_state[0], _joint_state[1]

        return q, dq

    def update_pinocchio(self, q, dq):
        self.robot.computeJointJacobians(q)
        self.robot.framesForwardKinematics(q)
        self.robot.centroidalMomentum(q, dq)

    def get_state_update_pinocchio(self):
        q, dq = self.get_state()
        self.update_pinocchio(q, dq)

        return q, dq

    def send_joint_command(self, tau):
        zeroGains = tau.shape[0] * (0.0,)

        p.setJointMotorControlArray(
            self.robotID,
            self.active_joint_ids,
            p.TORQUE_CONTROL,
            forces=tau,
            positionGains=zeroGains,
            velocityGains=zeroGains,
        )
